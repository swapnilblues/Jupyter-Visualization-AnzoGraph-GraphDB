#!/usr/bin/env python3

from http.client  import HTTPConnection
from urllib.parse import urlencode
import pandas as pd
import numpy as np
import json
from datetime import datetime, date, time

#------------------------------------------------------
# Runs SPARQL query at SPARQL endpoint and
# return results as a Python 'dict' (in the SPARQL1.1 results format)
# (for SPARQL1.1 results format refer: https://www.w3.org/TR/sparql11-results-json)
#
#       sparql_endpoint: 'host:port' ex: '192.168.0.64:7070', 'data.nobelprize.org'
#       sparql_query: ex: 'select (count(*) as ?c) {?s?p?o}'
#       headers: REST api headers ex: {'accept':'application/sparql-results+xml'}
#       params: SPARQL protocol params ex: {'default-graph-uri':['graph1','graph2']}
#------------------------------------------------------
#
def run_query(sparql_endpoint,sparql_query,headers={},params={}):
   # initialize headers
   req_hdrs = {'user-agent': 'AnzoGraph azg3.py'}
   for key,val in headers.items():
      req_hdrs[key.lower()] = val
   raw = True
   if 0 == len(req_hdrs.get('accept','')):
      # request result in json, if not specified
      req_hdrs['accept'] = 'application/sparql-results+json'
      raw = False
   # override any content-type set
   req_hdrs['content-type'] = 'application/x-www-form-urlencoded'

   # initialize params
   req_params = {}
   for p,v in params.items():
      req_params[p] = v
   req_params['query'] = sparql_query

   # urlencode query for sending
   docbody = urlencode(req_params,doseq=True)

   # send post request
   # create HTTP connection to SPARQL endpoint
   conn = HTTPConnection(sparql_endpoint,timeout=500) #may throw HTTPConnection exception
   conn.request('POST','/sparql',docbody,req_hdrs) #may throw exception

   # read response
   resp = conn.getresponse()
   if 200 != resp.status:
      errmsg = resp.read()
      conn.close()
      raise Exception('Query Error',errmsg)  # query processing errors - syntax errors, etc.

   # content-type header, and actual response data
   ctype = resp.getheader('content-type','text/html').lower()
   result = resp.read().lstrip()
   conn.close()

   # check response content-type header
   if raw or ctype.find('json') < 0:
      return result      # not a SELECT?

   # convert result in JSON string into python dict
   return json.loads(result)


#------------------------------------------------------
# Returns pandas DataFrame from the results of running a sparql_query at sparql_endpoint
#       sparql_endpoint: 'host:port' ex: '192.168.0.64:7070', 'data.nobelprize.org'
#       sparql_query: ex: 'select (count(*) as ?c) {?s?p?o}'
#       headers: REST api headers ex: {'accept':'application/sparql-results+xml'}
#       params: SPARQL protocol params ex: {'default-graph-uri':'tpch'}
#------------------------------------------------------
#
def create_dataframe(sparql_endpoint,sparql_query,headers={},params={}):
   # run query
   result = run_query(sparql_endpoint,sparql_query,headers,params)  # may throw exception
   # result is in SPARQL results format refer: https://www.w3.org/TR/sparql11-results-json/
   cols = result.get('head',{}).get('vars',[])
   rows = result.get('results',{}).get('bindings',[])

   # extract types and columnar data for rows
   coltype = {}
   nptype = {}
   coldata = {}
   for col in cols:
      coltype[col] = None
      coldata[col] = []
      nptype[col] = None

   # for all rows, save (columnar) data in coldata[] for each col
   for row in rows:
      for col in cols:
         cell = row.get(col,None)
         if cell is None:  # unbound value
            val = None
            if coltype[col] in ('byte','short','int','integer','float','double','decimal'):
               val = np.nan #missing numeric values as NaN
            coldata[col].append(val)
            continue
         # compute type and datum
         pdval = cell.get('value','')
         vtype = cell.get('type','')
         langtag = cell.get('xml:lang','')
         typeuri = cell.get('datatype','')
         pdtype = 'object'
         if vtype == 'uri':
            pdval = '<'+pdval+'>'
         elif langtag != '':
            pdval = '"'+pdval+'"@'+langtag
            coltype[col] = 'object'
         elif typeuri != '':
            #vtype in ('typed-literal')
            typeuri = typeuri.replace('http://www.w3.org/2001/XMLSchema#','')
            coltype[col] = typeuri if (coltype[col] is None or coltype[col] == typeuri) else 'object'
            pdtype,pdval = typed_value(typeuri,pdval)
         nptype[col] = pdtype if (coltype[col] != 'object') else 'object'
         coldata[col].append(pdval) # columnar data
   # instantiate DataFrame
   npdata = {}
   for col in cols:
      npdata[col] = np.array(coldata[col],dtype=np.dtype(nptype[col]))
   return pd.DataFrame(columns=cols,data=npdata)

def create_graph_from_dataframe(sparql_endpoint,graphname,df,headers={},params={}):
   insdata = []
   insdata.append('PREFIX xsd: <http://www.w3.org/2001/XMLSchema#> ')
   insdata.append('')
   insdata.append('DROP SILENT GRAPH <'+graphname+'> ;')
   insdata.append('INSERT DATA { GRAPH <'+graphname+'> {')
   xsdtypes = {}
   for col in df.columns:
      xsdtypes[col] = xsdtype_from_dtype(df.dtypes[col])
   for rownum,row in df.iterrows():
      rowstr = '[ a <dataframe#row>'.format(rownum)
      for col in df.columns:
         val = row[col]
         valtype = xsdtypes[col]
         if val == None or val == np.NaN or val == pd.NaT:
            continue
         rowstr += '; <{}> '.format(col.replace(' ','')) #sanitize - replace specials
         if '' == valtype:
            rowstr += '{}'.format(val)
         elif 'string' == valtype:
            rowstr += '"{}"'.format(val)
         else:
            rowstr += '"{}"^^xsd:{}'.format(val,valtype)
      rowstr += ' ].'
      insdata.append(rowstr)
   insdata.append('} }\n')
   run_query(sparql_endpoint,'\n'.join(insdata),headers,params)

# util: convert literal val into typed-value based on the typeuri
def typed_value(typeuri,val):
   # {"duration", ColTypeDuration},
   if typeuri in ('boolean'):
      return np.bool, 'true' == val
   elif typeuri in ('byte'):
      return np.byte, np.int8(val)
   elif typeuri in ('short'):
      return np.short, np.short(val)
   elif typeuri in ('integer','int','nonNegativeInteger'):
      return np.intc, np.int(val)
   elif typeuri in ('long'):
      return np.int_, np.int_(val)
   elif typeuri in ('float'):
      return np.single, np.float32(val)
   elif typeuri in ('double', 'decimal'):
      return np.double, np.float64(val)
   elif typeuri in ('dateTime'):
      return np.datetime64, datetime.fromisoformat(val)
   elif typeuri in ('date'):
      return pd.date, date.fromisoformat(val)
   elif typeuri in ('time'):
      return pd.time, time.fromisoformat(val)
   return 'object', val

def xsdtype_from_dtype(dtype):
   # numberic types
   if dtype in (np.int64,np.int32,np.int16,np.int8,np.double,np.float64,np.float32,np.float_,np.single,np.intc,np.byte,np.short,np.int_, np.byte,np.ubyte,np.ushort,np.uint,np.uintc,np.ulonglong, np.uint8,np.uint16,np.uint32,np.uint64):
      return ''
   if dtype in (np.bool, np.bool_) :
      return 'boolean'
   if dtype == np.datetime64:
      return 'dateTime'
   if dtype.name == 'object':
      return 'string'
   #print('dtype:', type(dtype), ', name:' , dtype.name)
   return 'string'
