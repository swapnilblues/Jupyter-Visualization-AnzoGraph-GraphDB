# %%

# !/usr/bin/env python3

from http.client import HTTPConnection
from urllib.parse import urlencode
from arcgis.mapping import create_symbol
import pandas as pd
import numpy as np
import json
from datetime import datetime, date, time


# ------------------------------------------------------
# Runs SPARQL query at SPARQL endpoint and
# return results as a Python 'dict' (in the SPARQL1.1 results format)
# (for SPARQL1.1 results format refer: https://www.w3.org/TR/sparql11-results-json)
#
#       sparql_endpoint: 'host:port' ex: '192.168.0.64:7070', 'data.nobelprize.org'
#       sparql_query: ex: 'select (count(*) as ?c) {?s?p?o}'
#       fmt - optional argument, if specified, returns results in a raw string format
#              possiblea values ('csv','json','xml'), any other format will be treated as 'json'
# ------------------------------------------------------
#
def run_query(sparql_endpoint, sparql_query, fmt=None):
    # create HTTP connection to SPARQL endpoint
    conn = HTTPConnection(sparql_endpoint, timeout=100)  # may throw HTTPConnection exception
    # urlencode query for sending
    docbody = urlencode({'query': sparql_query})
    # request result in json
    hdrs = {'Accept': 'application/sparql-results+json',
            'Content-type': 'application/x-www-form-urlencoded'}
    raw = False
    if fmt is not None:
        raw = True
        if fmt in ('xml', 'XML'):
            hdrs['Accept'] = 'application/sparql-results+xml'
        elif fmt in ('csv', 'CSV'):
            hdrs['Accept'] = 'text/csv, application/sparql-results+csv'

    # send post request
    conn.request('POST', '/sparql', docbody, hdrs)  # may throw exception

    # read response
    resp = conn.getresponse()
    if 200 != resp.status:
        errmsg = resp.read()
        conn.close()
        raise Exception('Query Error', errmsg)  # query processing errors - syntax errors, etc.

    # content-type header, and actual response data
    ctype = resp.getheader('content-type', 'text/html').lower()
    result = resp.read().lstrip()
    conn.close()

    # check response content-type header
    if raw or ctype.find('json') < 0:
        return result  # not a SELECT?

    # convert result in JSON string into python dict
    return json.loads(result)


# ------------------------------------------------------
# Returns pandas DataFrame from the results of running a sparql_query at sparql_endpoint
#       sparql_endpoint: 'host:port' ex: '192.168.0.64:7070', 'data.nobelprize.org'
#       sparql_query: ex: 'select (count(*) as ?c) {?s?p?o}'
# ------------------------------------------------------
#
def create_dataframe(sparql_endpoint, sparql_query):
    # run query
    result = run_query(sparql_endpoint, sparql_query)  # may throw exception
    # result is in SPARQL results format refer: https://www.w3.org/TR/sparql11-results-json/
    cols = result.get('head', {}).get('vars', [])
    rows = result.get('results', {}).get('bindings', [])

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
            cell = row.get(col, None)
            if cell is None:  # unbound value
                val = None
                if coltype[col] in ('byte', 'short', 'int', 'integer', 'float', 'double', 'decimal'):
                    val = np.nan  # missing numeric values as NaN
                coldata[col].append(val)
                continue
            # compute type and datum
            pdval = cell.get('value', '')
            vtype = cell.get('type', '')
            langtag = cell.get('xml:lang', '')
            typeuri = cell.get('datatype', '')
            pdtype = 'object'
            if vtype == 'uri':
                pdval = '<' + pdval + '>'
            elif langtag != '':
                pdval = '"' + pdval + '"@' + langtag
                coltype[col] = 'object'
            elif typeuri != '':
                # vtype in ('typed-literal')
                typeuri = typeuri.replace('http://www.w3.org/2001/XMLSchema#', '')
                coltype[col] = typeuri if (coltype[col] is None or coltype[col] == typeuri) else 'object'
                pdtype, pdval = typed_value(typeuri, pdval)
            nptype[col] = pdtype if (coltype[col] != 'object') else 'object'
            coldata[col].append(pdval)  # columnar data
    # instantiate DataFrame
    npdata = {}
    for col in cols:
        npdata[col] = np.array(coldata[col], dtype=np.dtype(nptype[col]))
    return pd.DataFrame(columns=cols, data=npdata)


# util: convert literal val into typed-value based on the typeuri
def typed_value(typeuri, val):
    # {"duration", ColTypeDuration},
    if typeuri in ('boolean'):
        return np.bool, 'true' == val
    elif typeuri in ('byte'):
        return np.byte, np.int8(val)
    elif typeuri in ('short'):
        return np.short, np.short(val)
    elif typeuri in ('integer', 'int', 'nonNegativeInteger'):
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


# %%

def createAirportQuery(origin):
    return '''PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
prefix : <https://ontologies.semanticarts.com/raw_data#>
prefix fl: <https://ontologies.semanticarts.com/flights/>
prefix owl: <http://www.w3.org/2002/07/owl#>
prefix skos:    <http://www.w3.org/2004/02/skos/core#>
CONSTRUCT { 
  	?orig fl:hasRouteTo ?dest .
  	?orig rdfs:label ?origCode . 
  	?dest rdfs:label ?destCode . 
  	fl:hasRouteTo rdfs:label "hasRouteTo" . 
}  
WHERE { GRAPH <airline_flight_network> {{
SELECT 
?orig ?dest ?origCode ?destCode ?miles 
    WHERE { 
        ?orig fl:terminalCode ?origCode .
        ?orig fl:hasRouteTo ?dest .
        ?dest fl:terminalCode ?destCode .
        << ?orig fl:hasRouteTo ?dest >> fl:distanceMiles ?miles .
        FILTER (?miles < 400)
        FILTER (?origCode = \'''' + origin + '''\')
  }
      }}}
'''


labelDict = {}


def createGraph(query,rootNode):
    #     print('Inside')
    flights = run_query('127.0.0.1:7070', query)

    x = flights.decode("utf-8")

    a = x.split(".\n")
    a = a[1: len(a) - 1]
    triples = set()
    for ele in a:
        ele = ele[:len(ele) - 1]
        triples.add(ele)
    # nodeNames = set()

    graph = []
    nodes = set()
    edges = set()

    # for ele in triples:
    #     arr = ele.split(' ')
    #     print(arr[0])

    for ele in triples:
        arr = ele.split(' ')
        p = arr[1].split('/')
        p = p[len(p) - 1]
        p = p[:len(p) - 1]

        if "label" in p:
            s = arr[0]
            o = arr[2][1:len(arr[2]) - 1]
            labelDict[s.lower()] = o
    # print(labelDict)

    for ele in triples:
        arr = ele.split(' ')
        s = arr[0]
        p = arr[1]
        o = arr[2]

        nodes.add(s)

        if arr[2][0] == '<' and arr[2][len(arr[2]) - 1] == '>':
            nodes.add(o)
            graph.append({'S': s, 'P': p, 'O': o})
            edges.add(p)

    nodes = nodes - edges

    elements = []
    for node in nodes:
        elements.append({'data': {'id': node,
                                  'label': labelDict.get(node.lower(), node),
                                  'expanded': False,
                                  'source': rootNode
                                  }
                         })
    for ele in graph:
        elements.append({'data': {'source': ele['S'],
                                  'target': ele['O'],
                                  'label': ele['P'],
                                  'labelLabel': labelDict.get(ele['P'].lower(), ele['P']),
                                  'sourceLabel': labelDict.get(ele['S'].lower(), ele['S']),
                                  'targetLabel': labelDict.get(ele['O'].lower(), ele['O'])
                                  }
                         })
    return elements


def getEdgeLabel(origin):
    return 'From Airport: ' + origin


def createGetNeighboringAirportQuery(origin):
    return '''PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    prefix fl: <https://ontologies.semanticarts.com/flights/>
    prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    select ?s ?p ?obj ?obj_type ?obj_label from <airline_flight_network>
            where {
                ?s ?p ?obj .
			    optional {  ?obj a ?obj_type . }
    		    optional {	?obj rdfs:label ?obj_label .  }
            VALUES ?s { 	''' + origin + '''} 
    filter(ISIRI(?obj_type))   
    }
    #	order by ?s 
    limit 10
    '''

def getNeighbours(query):
    df = create_dataframe('127.0.0.1:7070', query)
    return df


# def generateNodes(df):

import math


def generateNodes(df, sourceURI):
    # verify to check whether new nodes can be repetitve and accordingly create a set of nodes and then a list of newNodes
    newNodes = []

    # insert label of node into dict
    for i in df.index:
        if df['obj_label'][i]:
            labelDict[df['obj'][i].lower()] = df['obj_label'][i]

    for i in df.index:

        newNode = {'data': {'id': df['obj'][i],
                            'label': labelDict.get(df['obj'][i].lower(), df['obj'][i]),
                            'expanded': False,
                            'source': sourceURI
                            }
                   }
        if newNode not in newNodes:
            newNodes.append(newNode)
    #         print("0",newNode)
    return newNodes


def generateEdges(df):
    newEdges = []

    # insert label of edge into dict

    for i in df.index:

        newEdge = {'data': {'source': df['s'][i],
                            'target': df['obj'][i],
                            'label': df['p'][i],
                            'labelLabel': labelDict.get(df['p'][i].lower(), df['p'][i]),
                            'sourceLabel': labelDict.get(df['s'][i].lower(), df['s'][i]),
                            'targetLabel': labelDict.get(df['obj'][i].lower(), df['obj'][i])
                            }
                   }
        if newEdge not in newEdges:
            newEdges.append(newEdge)

    return newEdges


def removeNodes(element, nodeURI):
    copyElement = []

    for e in element:
        #         print("1.0",e)
        if e['data']['source'] != nodeURI:
            e['data']['expanded'] = False
            copyElement.append(e)
    return copyElement


# %%

# elements = createGraph('BOS')
# df = getNeighbours('<https://data.semanticarts.com/flights/_Airport_ACY>')

# x = generateNodes(df)
# x
# df
# for i in df.index:
#         print(df['s'][i]," ",df['p'][i]," ",df['obj'][i])

# generateNodes(df)


# %%

# import math
# def generateNodes(df):
#     for i in df.index:

#         t = df['obj_type'][i]

#         # insert label into dict

#         newNodes = []
#         if "Airport" in t:
#             newNodes.append({'data': {'id': df['obj'][i],
#                                       'label': labelDict.get(df['obj'][i].lower(),df['obj'][i])
#                                      }
#                            })
#     print(newNodes)
#     return newNodes


# x = generateNodes('BOS')
# print(x)

# print(math.isnan(df['obj_label'][5]))

# %%

# import json
# from jupyter_dash import JupyterDash
# import dash_cytoscape as cyto
# import dash_html_components as html
# import dash_core_components as dcc
# from demos import dash_reusable_components as drc
# from dash.dependencies import Input, Output, State

# app = JupyterDash(__name__)

# app.layout = html.Div([

#     html.Div(className='a',children = [
#     dcc.Dropdown(
#         id='dropdown-update-layout',
#         value='circle',
#         clearable=False,
#         options=[
#             {'label': name.capitalize(), 'value': name}
#             for name in ['grid', 'random', 'circle', 'cose', 'concentric']
#         ]
#     )]),
#     drc.NamedRadioItems(
#                     name='Select',
#                     id='radio-expand',
#                     options=drc.DropdownOptionsList(
#                         'Show Neighbors',
#                         'Hide Neighbors'
#                     ),
#                     value='Show Neighbors'
#                 ),
#     html.P(id='cytoscape-tapEdgeData-output1'),
#     html.P(id='cytoscape-tapNodeData-output'),
#     html.Div(className='b',children = [
#     cyto.Cytoscape(
#         id='cytoscape-update-layout',
#         layout={'name': 'circle'},
#         style={'width': '100%', 'height': '50vh'},
#         elements=elements,
#         stylesheet = [
#             {
#             'selector': 'node',
#             'style': {
#                 'content': 'data(label)',
#                 'background-color': 'blue',
#                 }
#             },
#             {
#             'selector': 'edge',
#             'style': {
#                 'content': 'data(labelLabel)',
#                 'curve-style': 'bezier',
#                 'target-arrow-color': 'red',
#                 'target-arrow-shape': 'triangle',
#                 'line-color': 'red'
#                 }
#             }
#         ]
#     )]),

#     html.P(id='cytoscape-tapEdgeData-output')
# ])


# @app.callback(Output('cytoscape-tapNodeData-output', 'children'),
#               [Input('cytoscape-update-layout', 'tapNodeData')])
# def displayTapNodeData(data):
# #     print('HH')
#     if data:
#         return "Airport selected: " + data['id']


# @app.callback(Output('cytoscape-tapEdgeData-output', 'children'),
#               [Input('cytoscape-update-layout', 'tapEdgeData')]
#              )
# def displayTapEdgeData(data):
#     if data:
#         return "Connection between " + data['source'].upper() + " and " + data['target'].upper() + " with edge value: " + data['label']


# @app.callback(Output('cytoscape-update-layout', 'layout'),
#               [Input('dropdown-update-layout', 'value')])
# def update_layout(layout):
#     return {
#         'name': layout,
#         'animate': True
#     }

# @app.callback(Output('cytoscape-update-layout', 'elements'),
#               [Input('cytoscape-update-layout', 'tapNodeData')],
#               [State('cytoscape-update-layout', 'elements')]
#              )
# def generate_elements(data,e):
#     if not data:
#         return e

#     if data['expanded'] == True:
#         return e
#     if data and e:

#         #changing extended to True for the node
#         for element in e:
#             if data['id'] == element.get('data').get('id'):
#                 element['data']['expanded'] = True
#                 break

#         nodeURI = data['id']
#         df = getNeighbours(nodeURI)
#         nodes = generateNodes(df,nodeURI)
#         edges = generateEdges(df)

#         for node in nodes:
#             if node not in e:
#                 e.append(node)

#         for edge in edges:
#             if edge not in e:
#                 e.append(edge)

#     return e

# # @app.callback(Output('output-container-button', 'children'),
# #               [Input('button', 'n_clicks')],
# #               [State('input-box', 'value')])
# # def update_output(n_clicks, value):
# #     return 'The input value was "{}" and the button has been clicked {} times'.format(
# #         value,
# #         n_clicks
# #     )


# port = '8089'
# host = '127.0.0.1'

# app.run_server(mode='inline',port = port, host = host)

# # print('App running on http://'+ host +':' + port +'/')

# # Node selected with both uri and label

# %%

# import json
# from jupyter_dash import JupyterDash
# import dash_cytoscape as cyto
# import dash_html_components as html
# import dash_core_components as dcc
# from dash.dependencies import Input, Output, State
# from demos import dash_reusable_components as drc
#
# app = JupyterDash(__name__)
#
# app.layout = html.Div([
#
#     html.Div(className='a', children=[
#         dcc.Dropdown(
#             id='dropdown-update-layout',
#             value='circle',
#             clearable=False,
#             options=[
#                 {'label': name.capitalize(), 'value': name}
#                 for name in ['grid', 'random', 'circle', 'cose', 'concentric']
#             ]
#         )]),
#     drc.NamedRadioItems(
#         name='Select',
#         id='radio-option',
#         options=drc.DropdownOptionsList(
#             'Show Neighbors'
#             #                         ,
#             #                         'Hide Neighbors'
#         ),
#         value='Show Neighbors'
#     ),
#
#     html.Div(className='b', children=[
#         cyto.Cytoscape(
#             id='cytoscape-update-layout',
#             layout={'name': 'circle'},
#             style={'width': '100%', 'height': '70vh'},
#             elements=elements,
#             stylesheet=[
#                 {
#                     'selector': 'node',
#                     'style': {
#                         'content': 'data(label)',
#                         'background-color': '#58FAF4',
#                     }
#                 },
#                 {
#                     'selector': 'edge',
#                     'style': {
#                         'content': 'data(labelLabel)',
#                         'curve-style': 'bezier',
#                         'target-arrow-color': 'black',
#                         'target-arrow-shape': 'triangle',
#                         'line-color': 'black'
#                     }
#                 }
#             ]
#         )]),
#     html.P(id='cytoscape-tapNodeData-output'),
#     html.P(id='cytoscape-tapEdgeData-output')
# ])
#
#
# ##########CALLBACKS##########
# @app.callback(Output('cytoscape-tapNodeData-output', 'children'),
#               [Input('cytoscape-update-layout', 'tapNodeData')])
# def displayTapNodeData(data):
#     #     print('HH')
#     if data:
#         return "Airport selected: " + data['id']
#
#
# @app.callback(Output('cytoscape-tapEdgeData-output', 'children'),
#               [Input('cytoscape-update-layout', 'tapEdgeData')]
#               )
# def displayTapEdgeData(data):
#     if data:
#         return "Connection between " + data['source'].upper() + " and " + data[
#             'target'].upper() + " with edge value: " + data['label']
#
#
# @app.callback(Output('cytoscape-update-layout', 'layout'),
#               [Input('dropdown-update-layout', 'value')])
# def update_layout(layout):
#     return {
#         'name': layout,
#         'animate': True
#     }
#
#
# # expand node by neighbors
# @app.callback(Output('cytoscape-update-layout', 'elements'),
#               [Input('cytoscape-update-layout', 'tapNodeData')],
#               [State('cytoscape-update-layout', 'elements')],
#               [State('radio-option', 'value')]
#               )
# def generate_elements(data, e, options):
#     #     print("abcd",data)
#     #     print("Radio Options",options)
#
#     print("AA")
#     if not data:
#         return e
#
#     print("Data", data['expanded'])
#     nodeURI = data['id']
#     if options == "Show Neighbors":
#
#         if data['expanded'] == True:
#             print("1")
#             return e
#
#         #     print("Label",data)
#
#         if data and e:
#
#             # changing extended to True for the node
#             for element in e:
#                 if data['id'] == element.get('data').get('id'):
#                     element['data']['expanded'] = True
#                     #                 print("Curr Node", element)
#                     break
#
#             #         print('node',nodeURI)
#             #         print("Label",label)
#             #         print('Here', type(e))
#             df = getNeighbours(nodeURI)
#             nodes = generateNodes(df, nodeURI)
#             #             print("Neighbors",nodes)
#             edges = generateEdges(df)
#
#             for node in nodes:
#                 if node not in e:
#                     e.append(node)
#
#             for edge in edges:
#                 if edge not in e:
#                     e.append(edge)
#
#         return e
#     elif options == "Hide Neighbors":
#
#         if data['expanded'] == False:
#             print("2")
#             return e
#         return removeNodes(e, nodeURI)
#
#
# port = '8098'
# host = '127.0.0.1'

# app.run_server(mode='inline', port=port, host=host)

# print('App running on http://'+ host +':' + port +'/')

# %%

