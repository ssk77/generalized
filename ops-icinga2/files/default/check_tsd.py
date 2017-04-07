#!/usr/bin/python
#
# Script which queries TSDB with a given metric and alerts based on
# supplied threshold.  Compatible with Nagios output format, so can be
# used as a nagios command.
#
# This file is part of OpenTSDB.
# Copyright (C) 2010-2012  The OpenTSDB Authors.
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 2.1 of the License, or (at your
# option) any later version.  This program is distributed in the hope that it
# will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
# of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU Lesser
# General Public License for more details.  You should have received a copy
# of the GNU Lesser General Public License along with this program.  If not,
# see <http://www.gnu.org/licenses/>.
#
#
# check_tsd -m mysql.slave.seconds_behind_master -t host=foo -t schema=mydb
#     -d 600 -a avg -x gt -w 50 -c 100
#

import httplib
import operator
import socket
import sys
import time
from optparse import OptionParser

options = None

def main(argv):
    """Pulls data out of the TSDB and do very simple alerting from Nagios."""

    global options
    parser = OptionParser(description='Simple TSDB data extractor for Nagios.')
    parser.add_option('-H', '--host', default='localhost', metavar='HOST',
            help='Hostname to use to connect to the TSD.')
    parser.add_option('-p', '--port', type='int', default=80, metavar='PORT',
            help='Port to connect to the TSD instance on.')
    parser.add_option('-m', '--metric', metavar='METRIC',
            help='Metric to query.')
    parser.add_option('-t', '--tag', action='append', default=[],
            metavar='TAG', help='Tags to filter the metric on.')
    parser.add_option('-d', '--duration', type='int', default=600,
            metavar='SECONDS', help='How far back to look for data.')
    parser.add_option('-D', '--downsample', default='none', metavar='METHOD',
            help='Downsample function, e.g. one of avg, min, sum, or max.')
    parser.add_option('-W', '--downsample-window', type='int', default=60,
            metavar='SECONDS', help='Window size over which to downsample.')
    parser.add_option('-a', '--aggregator', default='sum', metavar='METHOD',
            help='Aggregation method: avg, min, sum (default), max.')
    parser.add_option('-x', '--method', dest='comparator', default='gt',
            metavar='METHOD', help='Comparison method: gt, ge, lt, le, eq, ne.')
    parser.add_option('-r', '--rate', default=False,
            action='store_true', help='Use rate value as comparison operand.')
    parser.add_option('-w', '--warning', type='float', metavar='THRESHOLD',
            help='Threshold for warning.  Uses the comparison method.')
    parser.add_option('-c', '--critical', type='float', metavar='THRESHOLD',
            help='Threshold for critical.  Uses the comparison method.')
    parser.add_option('-v', '--verbose', default=False,
            action='store_true', help='Be more verbose.')
    parser.add_option('-T', '--timeout', type='int', default=60,
            metavar='SECONDS',
            help='How long to wait for the response from TSD.')
    parser.add_option('-E', '--no-result-ok', default=False,
            action='store_true',
            help='Return OK when TSD query returns no result.')
    parser.add_option('-I', '--ignore-recent', default=0, type='int',
            metavar='SECONDS', help='Ignore data points that are that'
            ' are that recent.')
    parser.add_option('-S', '--ssl', default=False, action='store_true',
            help='Make queries to OpenTSDB via SSL (https)')
    parser.add_option('-A', '--enable_client_aggregator', default=False, action='store_true',
            help='Enable client side aggregation of results from OpenTSDB')
    parser.add_option('-C', '--client_aggregator', default='sum', metavar='METHOD',
            help='Aggregation method for aggregating the results got from OpenTSDB: avg, min, sum (default), max.')

    (options, args) = parser.parse_args(args=argv[1:])

    # argument validation
    if options.comparator not in ('gt', 'ge', 'lt', 'le', 'eq', 'ne'):
        parser.error("Comparator '%s' not valid." % options.comparator)
    elif options.downsample not in ('none', 'avg', 'min', 'sum', 'max'):
        parser.error("Downsample '%s' not valid." % options.downsample)
    elif options.aggregator not in ('avg', 'min', 'sum', 'max'):
        parser.error("Aggregator '%s' not valid." % options.aggregator)
    elif options.client_aggregator not in ('avg', 'min', 'sum', 'max'):
        parser.error("Client Side Aggregator '%s' not valid." % options.client_aggregator)
    elif not options.metric:
        parser.error('You must specify a metric (option -m).')
    elif options.duration <= 0:
        parser.error('Duration must be strictly positive.')
    elif options.downsample_window <= 0:
        parser.error('Downsample window must be strictly positive.')
    elif options.critical is None and options.warning is None:
        parser.error('You must specify at least a warning threshold (-w) or a'
                     ' critical threshold (-c).')
    elif options.ignore_recent < 0:
        parser.error('--ignore-recent must be positive.')

    if not options.critical:
        options.critical = options.warning
    elif not options.warning:
        options.warning = options.critical

    # argument construction
    tags = ','.join(options.tag)
    if tags:
        tags = '{' + tags + '}'

    # URL building and fetching
    if options.downsample == 'none':
        downsampling = ''
    else:
        downsampling = '%ds-%s:' % (options.downsample_window,
                                    options.downsample)
    if options.rate:
        rate = 'rate:'
    else:
        rate = ''
    url = ('/q?start=%ss-ago&m=%s:%s%s%s%s&ascii&nagios'
           % (options.duration, options.aggregator, downsampling, rate,
              options.metric, tags))
    print 'url = {0}'.format(url)
    tsd = '%s:%d' % (options.host, options.port)
    if options.ssl:  # Pick the class to instantiate first.
      conn = httplib.HTTPSConnection
    else:
      conn = httplib.HTTPConnection
    if sys.version_info[0] * 10 + sys.version_info[1] >= 26:  # Python >2.6
      conn = conn(tsd, timeout=options.timeout)
    else:  # Python 2.5 or less, using the timeout kwarg will make it croak :(
      conn = conn(tsd)
    try:
      conn.connect()
    except socket.error, e:
      print "ERROR: couldn't connect to %s: %s" % (tsd, e)
      return 2
    if options.verbose:
        peer = conn.sock.getpeername()
        print 'Connected to %s:%d' % (peer[0], peer[1])
        conn.set_debuglevel(1)
    now = int(time.time())
    try:
      conn.request('GET', url)
      res = conn.getresponse()
      datapoints = res.read()
    except socket.error, e:
      print "ERROR: couldn't GET %s from %s: %s" % (url, tsd, e)
      return 3  # unknown status for nagios
    finally:
      conn.close()

    # if failure...
    if res.status not in (200, 202):
        print ('CRITICAL: status = %d when talking to %s:%d'
               % (res.status, options.host, options.port))
        if options.verbose:
            print 'TSD said:'
            print datapoints
        return 3 # unknown status for nagios

    # but we won!
    if options.verbose:
        print datapoints
    datapoints = datapoints.splitlines()

    def no_data_point():
        if options.no_result_ok:
            print 'OK: query did not return any data point (--no-result-ok)'
            return 0
        else:
            print 'CRITICAL: query did not return any data point'
            return 2

    if not len(datapoints):
        return no_data_point()

    comparator = operator.__dict__[options.comparator]
    rv = 0         # return value for this script
    badts = None   # Timestamp of the bad value we found, if any.
    badval = None  # Value of the bad value we found, if any.
    npoints = 0    # How many values have we seen?
    nbad = 0       # How many bad values have we seen?

    agg = None
    for datapoint in datapoints:
        datapoint = datapoint.split()
        ts = int(datapoint[1])
        delta = now - ts
        if delta > options.duration or delta <= options.ignore_recent:
            continue  # Ignore data points outside of our range.
        npoints += 1
        val = datapoint[2]
        if '.' in val:
            val = float(val)
        else:
            val = int(val)

        if options.enable_client_aggregator:
           if (npoints == 1):
              agg = val
           else:
              agg = aggregate(agg,val)
        else:
            bad = False  # Is the current value bad?
            # compare to warning/crit
            if comparator(val, options.critical):
                rv = 2
                bad = True
                nbad += 1
            elif rv < 2 and comparator(val, options.warning):
                rv = 1
                bad = True
                nbad += 1
            if (bad and
               (badval is None  # First bad value we find.
               or comparator(val, badval))):  # Worse value.
               badval = val
               badts = ts

    if options.enable_client_aggregator:
        if options.client_aggregator == 'avg':
           agg = agg/npoints;
        val = agg
        npoints = 1
        bad = False  # Is the current value bad?
        # compare to warning/crit
        if comparator(val, options.critical):
            rv = 2
            bad = True
            nbad += 1
        elif rv < 2 and comparator(val, options.warning):
            rv = 1
            bad = True
            nbad += 1
        if (bad and
            (badval is None  # First bad value we find.
            or comparator(val, badval))):  # Worse value.
            badval = val
            badts = ts

    if options.verbose and len(datapoints) != npoints:
        print ('ignored %d/%d data points for being more than %ds old'
               % (len(datapoints) - npoints, len(datapoints), options.duration))
    if not npoints:
        return no_data_point()
    if badts:
        if options.verbose:
            print 'worse data point value=%s at ts=%s' % (badval, badts)
        badts = time.asctime(time.localtime(badts))

    # in nrpe, pipe character is something special, but it's used in tag
    # searches.  Translate it to something else for the purposes of output.
    ttags = tags.replace("|",":")
    if not rv:
        print ('OK: %s%s: %d values OK, last=%r'
               % (options.metric, ttags, npoints, val))
    else:
        if rv == 1:
            level = 'WARNING'
            threshold = options.warning
        elif rv == 2:
            level = 'CRITICAL'
            threshold = options.critical
        print ('%s: %s%s %s %s: %d/%d bad values (%.1f%%) worst: %r @ %s'
               % (level, options.metric, ttags, options.comparator, threshold,
                  nbad, npoints, nbad * 100.0 / npoints, badval, badts))
    return rv

def aggregate(agg, val):
   global options
   if options.client_aggregator == 'max':
      agg = max(agg,val)
   elif options.client_aggregator == 'min':
      agg = min(agg,val)
   elif options.client_aggregator == 'sum':
      agg = agg + val
   elif options.client_aggregator == 'avg':
      agg = agg + val
   return agg


if __name__ == '__main__':
    sys.exit(main(sys.argv))
