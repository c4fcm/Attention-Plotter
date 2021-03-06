from __future__ import division

import calendar
import datetime
import json
import math
import pymongo
import time
import urllib
import urllib2
import xml.etree.ElementTree
from wtforms import SelectField, validators

from app import TaskStatus, db
from app.sources.source import Source, CreateSourceForm

mc_sentence = 'http://www.mediacloud.org/admin/query/sentences'
mc_wordcount = 'http://mediacloud.org/admin/query/wc'

class MediaCloud(Source):
    
    name = 'Media Cloud'

    def xml_to_result(self, xml_response):
        '''Convert solr xml response into json until the json API is ready.'''
        tree = xml.etree.ElementTree.fromstring(xml_response)
        result_elt = tree.find('result')
        result = {
            'numFound': result_elt.attrib['numFound']
        }
        return result

    def extract(self):
        """Fetch raw data into database."""
        project = db.projects.find_one({'_id': self.data['project_id']})
        start = 0
        rows_per_req = 500
        start_date = datetime.datetime.strptime(project['start'], '%Y-%m-%d')
        end_date = datetime.datetime.strptime(project['end'], '%Y-%m-%d')
        date = start_date
        delta = datetime.timedelta(days=1)
        # Loop through each date
        while date <= end_date:
            timestamp = calendar.timegm(date.timetuple())
            # Generate the query params
            fq = "publish_date:[%sT00:00:00Z TO %sT00:00:00Z] AND +media_sets_id:%s" % (
                date.strftime('%Y-%m-%d')
                , (date + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
                , self.data['media_set_id']
            )
            query = urllib.urlencode({
                'q':' AND '.join(project['keywords'])
                , 'fq': fq
                , 'rows':'0'
                , 'df':'sentence'
            })
            # Query the count
            url = '?'.join([mc_sentence, query])
            response = json.loads(urllib2.urlopen(url).read())['response']
            result = {
                'source_id': self.data['_id']
                , 'date': timestamp
                , 'numFound': response['numFound']
            }
            db.raw.insert(result)
            # Query related words
            url = '?'.join([mc_wordcount, query])
            count_result = json.loads(urllib2.urlopen(url).read())
            for word in count_result:
                word.update({
                    'source_id': self.data['_id']
                    , 'date': timestamp
                })
                db.words.insert(word)
            # Increment the date
            date += delta
    
    def transform(self):
        """Transform raw data"""
        project = db.projects.find_one({'_id': self.data['project_id']})
        start_date = datetime.datetime.strptime(project['start'], '%Y-%m-%d')
        end_date = datetime.datetime.strptime(project['end'], '%Y-%m-%d')
        # Normalize counts
        counts = list(db.raw.find({'source_id': self.data['_id']}))
        max_count = max([int(data['numFound']) for data in counts])
        for data in counts:
            data['normalized'] = float(data['numFound']) / max_count
        db.transformed.insert(counts)
        # TF-IDF related terms
        words = list(db.words.find({'source_id': self.data['_id']}))
        doc_count = {}
        total = (end_date - start_date).days + 1
        for word in words:
            doc_count[word['term']] = doc_count.get(word['term'],0) + 1
        for word in words:
            word['tfidf'] = word['count'] * math.log(total / doc_count[word['term']])
            db.transformedwords.insert(word)
    
    def load(self):
        """Create json results formatted for d3 use."""
        for data in db.transformed.find({'source_id':self.data['_id']}):
            words = list(db.transformedwords.find({
                'source_id':self.data['_id']
                , 'date':data['date']
            }, sort=[('tfidf', pymongo.DESCENDING)], limit=100))
            db.results.insert({
                'source_id': self.data['_id']
                , 'project_id': self.data['project_id']
                , 'label': self.data['label']
                , 'date': data['date']
                , 'value': data['normalized']
                , 'raw': data['numFound']
                , 'words': [{'term':word['term'], 'value':word['tfidf']} for word in words]
            })
    
    @classmethod
    def create_form(cls):
        class CreateMCForm(CreateSourceForm):
            media_id = SelectField('Media Set', choices=[('1', 'Default')])
        return CreateMCForm
    
    @classmethod
    def create(cls, request, username, project_name):
        create_form = (cls.create_form())()
        if create_form.validate_on_submit():
            source = super(MediaCloud, cls).create(request, username, project_name)
            source['media_set_id'] = create_form.media_id.data
        else:
            return {}
        return source
