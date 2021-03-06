import requests
import click
import os, sys
from daemonize import Daemonize
import time
import logging
import json
from time import gmtime, strftime
import sqlite3
import numpy as np

from exchanges.kraken import Kraken 
from exchanges.yobit import Yobit
from exchanges.livecoin import Livecoin
from exchanges.poloniex import Poloniex
from exchanges.exmo import Exmo

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(BASE_DIR, 'data.db')

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

cursor.execute(
  '''
    CREATE TABLE IF NOT EXISTS ticker (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pair TEXT,
      ask_value REAL,
      ask_volume REAL,
      bid_value REAL,
      bid_volume REAL,
      ts datetime default current_timestamp
    );
  '''
)

ASSET_PAIRS = None

def run_async(func):
  from threading import Thread
  from functools import wraps

  @wraps(func)
  def async_func(*args, **kwargs):
    func_hl = Thread(target = func, args = args, kwargs = kwargs)
    func_hl.start()
    return func_hl

  return async_func

def getDeriv(array, dimension=1):
  result = 0
  if dimension == 1:
    result = np.average(
      np.gradient(
        np.array(
          array,
          dtype=float
        )
      )
    )
  elif dimension == 2:
    result = np.average(
      np.gradient(
        np.gradient(
          np.array(
            array,
            dtype=float
          )
        )
      )
    )

  if result == 0:
    return 0
  else:
    return '%.8f' % result

def getExchange(name):
  if name == 'kraken':
    return Kraken()
  if name == 'yobit':
    return Yobit()
  if name == 'livecoin':
    return Livecoin()
  if name == 'poloniex':
    return Poloniex()
  if name == 'exmo':
    return Exmo()

def getFormattedTime():
  return strftime("%d.%m.%Y %H:%M:%S", gmtime())

def getAssetPairs(exchange):
  global ASSET_PAIRS

  if not ASSET_PAIRS:
    ASSET_PAIRS = getExchange(exchange).getAssetPairs()

  return ASSET_PAIRS

def getTickers(exchange, pairs, mode):
  if pairs:
    return getExchange(exchange).getTickers(pairs.split(','), mode)
  else:
    return getExchange(exchange).getTickers(getAssetPairs(exchange).keys(), mode)

def getFilename(exchange, pairs):
  return getExchange(exchange).getFilename(pairs)

@click.option('--exchange', required=True)
@click.option('--pairs', nargs=1, required=False)
@click.command(name='daemon-stop', short_help='Stops daemon')
def daemon_stop(exchange, pairs):
  name = getFilename(exchange, pairs)
  fh = logging.FileHandler('%s.log' % name, "a")
  logger.addHandler(fh)
  logger.info('INFO [%s]: Daemon stopped' % getFormattedTime())
  pid_filename = './%s.pid' % name
  try:
    with open(pid_filename, "r") as pid_file:
      pid = pid_file.read()
      os.system("kill -9 %d" % int(pid))
      os.remove(pid_filename)
      click.echo(click.style('Daemon stopped', fg='yellow'))
  except FileNotFoundError:
    click.echo(click.style('There is no such daemon started', fg='red'))

@click.option('--exchange', required=True)
@click.option('--pairs', nargs=1, required=False)
@click.option('--timeout', nargs=1, default=15)
@click.option('--shout/--no-shout', default=False)
@click.option('--local/--no-local', default=False)
@click.option('--mode')
@click.command(name='daemon-start', short_help='Starts daemon on exact exchange & pairs list (delimited by comma)')
def daemon_start(exchange, pairs, timeout, shout, local, mode):
  def run_daemon():
    conn = sqlite3.connect(db_path, check_same_thread=False)
    cursor = conn.cursor()
    history = []

    @run_async
    def runFunc():
      try:
        start_time = time.time()
        ts = int(time.time())
        tickers = getTickers(exchange, pairs, mode)
        history.append(tickers)

        if len(history) > 3:
          history.pop(0)

        if len(history) == 3:
          for index, (key, item) in enumerate(tickers.items()):
            item['meta'] = {
              'ask_deriv': getDeriv([ item[key]['ask']['value'] for item in history[:2] ], 1),
              'bid_deriv': getDeriv([ item[key]['bid']['value'] for item in history[:2] ], 1),
              'ask_deriv2': getDeriv([ item[key]['ask']['value'] for item in history ], 2),
              'bid_deriv2': getDeriv([ item[key]['bid']['value'] for item in history ], 2),
            }

        if local:
          tickersToInsert = []

          for index, (key, item) in enumerate(tickers.items()):
            tickersToInsert.append((key, item['ask']['value'], item['ask']['volume'], item['bid']['value'], item['bid']['volume'], ts))

          cursor.executemany('''
            INSERT INTO ticker (pair, ask_value, ask_volume, bid_value, bid_volume, ts)
            VALUES (?, ?, ?, ?, ?, ?)
          ''', tickersToInsert)
          conn.commit()
        else:
          requests.post('http://127.0.0.1:8080/collect/ticker/%s' % exchange, json={
            'tickers': {
              'data': tickers,
              'meta': {
                'ts': ts
              }
            }
          })

        execTime = '%.3f' % (time.time() - start_time)

        if shout:
          logger.info('INFO [%s]:\nPayload %s\nExecution time: %s\n-----------------------' % (getFormattedTime(), json.dumps(tickers, sort_keys=True, indent=4), execTime))
      except Exception as e:
        exc_type, exc_obj, exc_tb = sys.exc_info()
        fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
        logger.error('ERROR [%s]: %s %s %s %s' % (getFormattedTime(), e, exc_type, fname, exc_tb.tb_lineno))

    while True:
      runFunc()
      time.sleep(timeout)

  name = getFilename(exchange, pairs)
  pid_filename='./%s.pid' % name
  fh = logging.FileHandler('%s.log' % name, "a")
  logger.addHandler(fh)
  keep_fds = [fh.stream.fileno()]
  daemon = Daemonize(app=name, pid=pid_filename, action=run_daemon, keep_fds=keep_fds)
  logger.info('INFO [%s]: Daemon started' % getFormattedTime())
  click.echo(click.style('Daemon started, you\'re good :)', fg='green'))

  daemon.start()

@click.option('--exchange', required=True)
@click.command(name='list', short_help='Lists all the possible pairs on the concrete exchange to operate with', help='You can use the pair sysname (like XETHZUSD) in the other commands')
def list(exchange):
  pairs = getAssetPairs(exchange)
  for index, (key, item) in enumerate(pairs.items()):
    print('%s. %s (%s <-> %s)' % (index + 1, key, item['from'], item['to']))

@click.option('--exchange', required=True)
@click.option('--pairs', nargs=1, required=True)
@click.command(name='ticker', short_help='Fetches the ticker by pairs list (delimited by comma)')
def ticker(exchange, pairs):
  tickers = getTickers(exchange, pairs)
  for index, (key, item) in enumerate(tickers.items()):
    print('=== %s === ' % key)
    print('ask: %s\nbid: %s\nvolume: %s' % (item['ask'], item['bid'], item['volume']))

@click.command(name='exchange-list', short_help='List of all the possible exchanges to work on')
def exchange_list():
  for index, filename in enumerate([file for file in os.listdir('./exchanges') if file.endswith('.py') and not file.startswith('__')]):
    print('%s. %s' % (index + 1, filename.split('.')[0]))

@click.group()
def cli():
  pass
cli.add_command(list)
cli.add_command(ticker)
cli.add_command(daemon_start)
cli.add_command(daemon_stop)
cli.add_command(exchange_list)

if __name__ == '__main__':
  cli()