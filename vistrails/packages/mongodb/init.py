###############################################################################
##
## Copyright (C) 2014-2015, New York University.
## Copyright (C) 2011-2014, NYU-Poly.
## Copyright (C) 2006-2011, University of Utah.
## All rights reserved.
## Contact: contact@vistrails.org
##
## This file is part of VisTrails.
##
## "Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
##  - Redistributions of source code must retain the above copyright notice,
##    this list of conditions and the following disclaimer.
##  - Redistributions in binary form must reproduce the above copyright
##    notice, this list of conditions and the following disclaimer in the
##    documentation and/or other materials provided with the distribution.
##  - Neither the name of the New York University nor the names of its
##    contributors may be used to endorse or promote products derived from
##    this software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO,
## THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR
## PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR
## CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL,
## EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO,
## PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
## OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY,
## WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR
## OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF
## ADVISED OF THE POSSIBILITY OF SUCH DAMAGE."
##
###############################################################################

from __future__ import division

from pymongo import MongoClient

from vistrails.core.modules.vistrails_module import Module


class MongoDatabase(Module):
    """Connects to MongoDB and selects a database.
    """
    _input_ports = [('host', '(basic:String)',
                     {'optional': True, 'defaults': '["localhost"]'}),
                    ('port', '(basic:Integer)',
                     {'optional': True}),
                    ('database', '(basic:String)')]
    _output_ports = [('database', '(MongoDatabase)')]

    def compute(self):
        kwargs = {'host': self.get_input('host')}
        if self.has_input('port'):
            kwargs['port'] = self.get_input('port')
        client = MongoClient(**kwargs)

        database = client.get_database(self.get_input('database'))

        self.set_output('database', database)


# Database operations

class CreateCollection(Module):
    """Creates a collection in a MongoDB database.
    """
    _input_ports = [('database', MongoDatabase),
                    ('collection', '(basic:String)')]
    _output_ports = [('database', MongoDatabase)]

    def compute(self):
        database = self.get_input('database')
        collection = self.get_input('collection')

        database.create_collection(collection)

        self.set_output('database', database)


class DropCollection(Module):
    """Drops a collection from a MongoDB database.
    """
    _input_ports = [('database', MongoDatabase),
                    ('collection', '(basic:String)')]
    _output_ports = [('database', MongoDatabase)]

    def compute(self):
        database = self.get_input('database')
        collection = self.get_input('collection')

        database.drop_collection(collection)

        self.set_output('database', database)


class RenameCollection(Module):
    """Renames a collection in a MongoDB database.
    """
    _input_ports = [('database', MongoDatabase),
                    ('collection', '(basic:String)'),
                    ('new_name', '(basic:String)')]
    _output_ports = [('database', MongoDatabase)]

    def compute(self):
        database = self.get_input('database')
        old_name = self.get_input('collection')
        new_name = self.get_input('new_name')

        database[old_name].rename(new_name)

        self.set_output('database', database)


_modules = [MongoDatabase, CreateCollection, DropCollection, RenameCollection]


# Data operations

class BaseCollectionOperation(Module):
    _input_ports = [('database', MongoDatabase),
                    ('collection', '(basic:String)')]
    _output_ports = [('database', MongoDatabase)]

    collection_op_out = None

    def compute(self):
        database = self.get_input('database')
        collection = self.get_input('collection')

        out = self.collection_operation(database[collection])
        if self.collection_op_out is not None:
            self.set_output(self.collection_op_out, out)

        self.set_output('database', database)

    def collection_operation(self, collection):
        raise NotImplementedError


_modules.append(BaseCollectionOperation)


def collection_op(input_ports, output=None):
    def wrapper(func):
        dct = {'_input_ports': input_ports,
               'collection_operation': func}
        if output:
            dct['_output_ports'] = [output]
            dct['collection_op_out'] = output[0]
        _modules.append(type(func.func_name, (BaseCollectionOperation,), dct))
        return func
    return wrapper


@collection_op([('document', '(basic:Dictionary)')])
def InsertOne(self, coll):
    coll.insert_one(self.get_input('document'))


@collection_op([('filter', '(basic:Dictionary)'),
                ('document', '(basic:Dictionary)')])
def ReplaceOne(self, coll):
    coll.replace_one(self.get_input('filter'), self.get_input('document'))


@collection_op([('filter', '(basic:Dictionary)'), ('document', '(basic:Dictionary)'),
                ('insert_if_nomatch', '(basic:Boolean)',
                 {'optional': True, 'defaults': ['True']})])
def UpdateOne(self, coll):
    coll.update_one(self.get_input('filter'),
                    self.get_input('document'),
                    upsert=self.get_input('insert_if_nomatch'))


@collection_op([('filter', '(basic:Dictionary)')])
def DeleteOne(self, coll):
    coll.delete_one(self.get_input('filter'))


@collection_op([('filter', '(basic:Dictionary)')])
def DeleteMany(self, coll):
    coll.delete_many(self.get_input('filter'))


@collection_op([('pipeline', '(basic:List)')],
               output=('results', '(basic:List)'))
def Aggregate(self, coll):
    return list(coll.aggregate(self.get_input('pipeline')))


@collection_op([('filter', '(basic:Dictionary)'),
                ('limit', '(basic:Integer)', {'optional': True})],
               output=('results', '(basic:List)'))
def Find(self, coll):
    return list(coll.find(self.get_input('filter'),
                          limit=self.force_get_input('limit', 0)))


@collection_op([('filter', '(basic:Dictionary)')],
               output=('document', '(basic:Dictionary)'))
def FindOne(self, coll):
    return coll.find_one(self.get_input('filter'))


@collection_op([('filter', '(basic:Dictionary)')],
               output=('old_document', '(basic:Dictionary)'))
def FindOneAndDelete(self, coll):
    return coll.find_one_and_delete(self.get_input('filter'))


@collection_op([('filter', '(basic:Dictionary)'), ('document', '(basic:Dictionary)')],
               output=('old_document', '(basic:Dictionary)'))
def FindOneAndReplace(self, coll):
    return coll.find_one_and_replace(self.get_input('filter'),
                                     self.get_input('document'))


@collection_op([('filter', '(basic:Dictionary)'),
                ('update', '(basic:Dictionary)')],
               output=('old_document', '(basic:Dictionary)'))
def FindOneAndUpdate(self, coll):
    return coll.find_one_and_update(self.get_input('filter'),
                                    self.get_input('update'))


@collection_op([('filter', '(basic:Dictionary)', {'optional': True})],
               output=('count', '(basic:Integer)'))
def Count(self, coll):
    return coll.count(self.force_get_input('filter'))


@collection_op([('key', '(basic:String)'), ('filter', '(basic:Dictionary)')],
               output=('results', '(basic:List)'))
def Distinct(self, coll):
    return list(coll.distinct(self.get_input('key'), self.get_input('filter')))


@collection_op([('key', '(basic:List)'), ('condition', '(basic:Dictionary)'),
                ('initial', '(basic:Variant)'), ('reduce', '(basic:String)'),
                ('finalize', '(basic:String)')],
               output=('results', '(basic:List)'))
def Group(self, coll):
    return list(coll.group(self.get_input('key'), self.get_input('condition'),
                           self.get_input('initial'), self.get_input('reduce'),
                           self.force_get_input('finalize', None)))


@collection_op([('map', '(basic:String)'), ('reduce', '(basic:String)'),
                ('out', '(basic:String)')],
               output=('results', '(basic:List)'))
def MapReduce(self, coll):
    return coll.map_reduce(self.get_input('map'), self.get_input('reduce'),
                           self.get_input('out')).find()
