import requests
import krakenex

class Kraken:
  def getAssetPairs():
    kraken = krakenex.API()

    try:
      response = kraken.query_public('AssetPairs')

      if response['error']:
        # TODO: process error
        pass
      else:
        result = {}
        for index, (key, item) in enumerate(response['result'].items()):
          result[key] = { 'from': item['base'], 'to': item['quote'] }
        return result

    except requests.exceptions.HTTPError as e:
      # TODO: process error
      pass

    return assetPairs

  def getTickers(pairs):
    kraken = krakenex.API()

    try:
      response = kraken.query_public('Ticker', { 'pair' : pairs, })

      if response['error']:
        # TODO: process error
        pass
      else:
        result = {}
        for index, (key, item) in enumerate(response['result'].items()):
          result[key] = { 'ask': '%.8f' % item['a'][0], 'bid': '%.8f' % item['b'][0], 'volume': '%.8f' % item['v'][0] }
        return result

    except requests.exceptions.HTTPError as e:
      # TODO: process error
      pass