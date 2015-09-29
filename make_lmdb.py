import sys
import os
import numpy
import csv
import lmdb
import caffe
import random

CSV_FORMATS = {
    "DUDE_SCOREDATA": {
    	"delimiter":' ',
        "id":2,
        "group":1,
        "data":list(range(4, 65)),
        "label":[0]
    },

    "TEST_DATA": {
    	"delimiter":',',
    	"id":0,
    	"group":1,
    	"data":[2],
    	"label":[3]
    }
}

USAGE = "python make_lmdb.py <input> <format> <partitions> <output>\n"



class Database:

	def __init__(self, file_=None, format_=None):

		if file_ is not None and format_ is not None:
			self.read_csv()

		else:
			self._source = None
			self._format = None

			self._samples = []
			self._groups  = {}
			self._parts = []

			self._nbytes = 0


	def read_csv(self, file_, format_):

		# parse the csv_file in a known format
		csv_file   = open(file_, "r")
		csv_format = CSV_FORMATS[format_]
		csv_reader = csv.reader(csv_file, delimiter=csv_format["delimiter"])
		print(csv_format)

		self._source = file_
		self._format = csv_format
		self._parts = []
		# create a Database.Sample() object for each row in the csv_file
		# also keep track of all groups present in the data in a set()
		for row in csv_reader:
			s = Database.Sample(self, row[csv_format["id"]], row[csv_format["group"]],
				               [row[i] for i in csv_format["data"]],
				               [row[i] for i in csv_format["label"]])
			self._samples.append(s)

			if s._group in self._groups:
				self._groups[s._group].append(s)
			else:
				print(s._group)
				self._groups[s._group] = [s]
		
		# get a *rough* estimate of the number of bytes of data by summing the numpy.array() bytes
		self._nbytes = 8 * (len(self._format["data"]) + len(self._format["label"])) * len(self._samples)
		print(str(self._nbytes) + " bytes read")
		csv_file.close()


	def write_lmdb(self, dir_):

		# for each partition in the database
		for i in range(self._nparts):

			partition  = self._parts[i]
			source_file = os.path.basename(self._source)

			# we need to create 4 lmdbs- training data, training label, test data, and test label
			train_data_path  = os.path.join(dir_, source_file+"."+str(i)+".train.data")
			train_label_path = os.path.join(dir_, source_file+"."+str(i)+".train.label")
			test_data_path   = os.path.join(dir_, source_file+"."+str(i)+".test.data")
			test_label_path  = os.path.join(dir_, source_file+"."+str(i)+".test.label")
			
			# open the memory mapped environment associated with each lmdb
			train_data_lmdb  = lmdb.open(train_data_path,  map_size=2*self._nbytes)
			train_label_lmdb = lmdb.open(train_label_path, map_size=2*self._nbytes)
			test_data_lmdb   = lmdb.open(test_data_path,   map_size=2*self._nbytes)
			test_label_lmdb  = lmdb.open(test_label_path,  map_size=2*self._nbytes)

			# writing training set data and labels
			with train_data_lmdb.begin(write=True) as data_txn:
				with train_label_lmdb.begin(write=True) as label_txn:
					for s in partition.train_set():
						data_datum  = caffe.io.array_to_datum(s._data)
						label_datum = caffe.io.array_to_datum(s._label)
						data_txn.put(key=s._id.encode("ascii"), value=data_datum.SerializeToString())
						label_txn.put(key=s._id.encode("ascii"), value=label_datum.SerializeToString())

			# write test set data and labels
			with test_data_lmdb.begin(write=True) as data_txn:
				with test_label_lmdb.begin(write=True) as label_txn:
					for s in partition.test_set():
						data_datum  = caffe.io.array_to_datum(s._data)
						label_datum = caffe.io.array_to_datum(s._label)
						data_txn.put(key=s._id.encode("ascii"), value=data_datum.SerializeToString())
						label_txn.put(key=s._id.encode("ascii"), value=label_datum.SerializeToString())

			# close the lmdb environments
			train_data_lmdb.close()
			train_label_lmdb.close()
			test_data_lmdb.close()
			test_label_lmdb.close()
	
	def balanced_partition(self, n):

		# sort the groups in a list based on number of samples
		sorted_groups = [(g, len(self._groups[g])) for g in self._groups]
		sorted_groups.sort(key=lambda tup: tup[1], reverse=True)

		index = 0
		forward = True
		folds = [[] for i in range(n)]
		for g in sorted_groups:
			folds[index].append(g[0])
			if forward:
				if index < len(self._groups):
					index += 1
				else:
					forward = False
			else:
				if index > 0:
					index -= 1
				else:
					forward = True

		for i in range(n):
			test_set = folds.[i]
			train_set = folds[:i] + folds[i+1:]
			self._parts = Database.Partition(self, train_set, test_set)


	class Partition:

		def __init__(self, db, train, test):

			self._db = db
			self._train_set = set(train)
			self._test_set  = set(test)

		def train_set(self):

			for s in self._db._samples:
				if s._group in self._train_set:
					yield s

		def test_set(self):

			for s in self._db._samples:
				if s._group in self._test_set:
					yield s


	class Sample:

		def __init__(self, db, id_, group, data, label):

			self._id    = id_
			self._group = group
			self._data  = numpy.empty((len(db._format["data"]), 1, 1),  dtype=numpy.float64)
			self._label = numpy.empty((len(db._format["label"]), 1, 1), dtype=numpy.float64)
			for i in range(len(db._format["data"])):  self._data[i, 0, 0]  = data[i]
			for i in range(len(db._format["label"])): self._label[i, 0, 0] = label[i]





if __name__ == "__main__":

	usage_format = USAGE.strip("\n").split()[1:]
	if len(sys.argv) < len(usage_format):
		print("Usage: " + USAGE)
		sys.exit(1)

	file_arg   = sys.argv[usage_format.index("<input>")]
	format_arg = sys.argv[usage_format.index("<format>")]
	parts_arg  = sys.argv[usage_format.index("<partitions>")]
	output_arg = sys.argv[usage_format.index("<output>")]

	print("Gathering data from " + file_arg)
	try: db = Database(file_arg, format_arg)
	except IOError:
		print("Error: could not access the input file")
		sys.exit(1)
	except KeyError:
		print("Error: unknown input file format")
		sys.exit(1)

	print("Generating " + parts_arg + " partitions")
	db.balanced_partition(num=int(parts_arg))

	print("Converting to lmdb format in " + output_arg)
	try: db.write_lmdb(output_arg)
	except IOError:
		print("Error: could not access the output location")
		sys.exit(1)

	print("Done, without errors.")
	sys.exit(0)