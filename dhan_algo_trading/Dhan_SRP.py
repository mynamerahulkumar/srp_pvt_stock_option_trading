from dhanhq import dhanhq
try:
	from dhanhq import DhanContext, MarketFeed, OrderUpdate
except ImportError:
	DhanContext = None
	MarketFeed = None
	OrderUpdate = None
import mibian
import datetime
import numpy as np
import pandas as pd
import traceback
import pytz
import requests
import pdb
import os
from pathlib import Path
import time
import json
from pprint import pprint
import logging
import warnings
from typing import Tuple, Dict, Any, Optional
from collections import Counter
import urllib.parse

warnings.filterwarnings("ignore", category=FutureWarning)
print("Codebase Version 2.8 : Solved - Strike Selection Issue")

NIFTY50_SECURITY_IDS = {
	"ADANIENT": 25,
	"ADANIPORTS": 15083,
	"APOLLOHOSP": 157,
	"ASIANPAINT": 236,
	"AXISBANK": 5900,
	"BAJAJ-AUTO": 16669,
	"BAJFINANCE": 317,
	"BAJAJFINSV": 16675,
	"BEL": 383,
	"BHARTIARTL": 10604,
	"CIPLA": 694,
	"COALINDIA": 20374,
	"DRREDDY": 881,
	"EICHERMOT": 910,
	"ETERNAL": 5097,
	"GRASIM": 1232,
	"HCLTECH": 7229,
	"HDFCBANK": 1333,
	"HDFCLIFE": 467,
	"HEROMOTOCO": 1348,
	"HINDALCO": 1363,
	"HINDUNILVR": 1394,
	"ICICIBANK": 4963,
	"INDUSINDBK": 5258,
	"INFY": 1594,
	"ITC": 1660,
	"JIOFIN": 18143,
	"JSWSTEEL": 11723,
	"KOTAKBANK": 1922,
	"LT": 11483,
	"M&M": 2031,
	"MARUTI": 10999,
	"NESTLEIND": 17963,
	"NTPC": 11630,
	"ONGC": 2475,
	"POWERGRID": 14977,
	"RELIANCE": 2885,
	"SBILIFE": 21808,
	"SHRIRAMFIN": 4306,
	"SBIN": 3045,
	"SUNPHARMA": 3351,
	"TATACONSUM": 3432,
	"TATASTEEL": 3499,
	"TCS": 11536,
	"TECHM": 13538,
	"TITAN": 3506,
	"TRENT": 1964,
	"ULTRACEMCO": 11532,
	"WIPRO": 3787,
	"TMCV": 759782,
	"TMPV": 3456,
}


class Dhansrp:    
	clientCode                                      : str
	interval_parameters                             : dict
	instrument_file                                 : pd.core.frame.DataFrame
	step_df                                         : pd.core.frame.DataFrame
	index_step_dict                                 : dict
	index_underlying                                : dict
	call                                            : str
	put                                             : str

	def __init__(self,ClientCode:str=None,token_id:str=None,config_path:str=None,enable_file_logging:bool=False,instrument_cache_path:str=None,persist_instrument_file:bool=False):
		'''
		Clientcode                              = The ClientCode in string 
		token_id                                = The token_id in string 
		'''
		self.config_path = config_path
		self.enable_file_logging = enable_file_logging
		self.instrument_cache_path = instrument_cache_path
		self.persist_instrument_file = persist_instrument_file
		self.logger = self._setup_logger(enable_file_logging=enable_file_logging)
		logging.info('Dhan.py  started system')
		logging.getLogger("requests").setLevel(logging.WARNING)
		logging.getLogger("urllib3").setLevel(logging.WARNING)
		self.logger.info("STARTED THE PROGRAM")

		try:
			self.status 							= dict()
			self.token_and_exchange 				= dict()
			self.get_login(ClientCode,token_id)
			self.token_and_exchange 				= {}
			self.interval_parameters                = {'minute':  60,'2minute':  120,'3minute':  180,'4minute':  240,'5minute':  300,'day':  86400,'10minute':  600,'15minute':  900,'30minute':  1800,'60minute':  3600,'day':86400}
			self.index_underlying                   = {"NIFTY 50":"NIFTY","NIFTY BANK":"BANKNIFTY","NIFTY FIN SERVICE":"FINNIFTY","NIFTY MID SELECT":"MIDCPNIFTY"}
			self.segment_dict                       = {"NSECM": 1, "NSEFO": 2, "NSECD": 3, "BSECM": 11, "BSEFO": 12, "MCXFO": 51}
			self.index_step_dict                    = {'MIDCPNIFTY':25,'SENSEX':100,'BANKEX':100,'NIFTY': 50, 'NIFTY 50': 50, 'NIFTY BANK': 100, 'BANKNIFTY': 100, 'NIFTY FIN SERVICE': 50, 'FINNIFTY': 50}
			self.token_dict 						= {'NIFTY':{'token':26000,'exchange':'NSECM'},'NIFTY 50':{'token':26000,'exchange':'NSECM'},'BANKNIFTY':{'token':26001,'exchange':'NSECM'},'NIFTY BANK':{'token':26001,'exchange':'NSECM'},'FINNIFTY':{'token':26034,'exchange':'NSECM'},'NIFTY FIN SERVICE':{'token':26034,'exchange':'NSECM'},'MIDCPNIFTY':{'token':26121,'exchange':'NSECM'},'NIFTY MID SELECT':{'token':26121,'exchange':'NSECM'},'SENSEX':{'token':26065,'exchange':'BSECM'},'BANKEX':{'token':26118,'exchange':'BSECM'}}
			self.intervals_dict 					= {'minute': 3, '2minute':4, '3minute': 4, '5minute': 5, '10minute': 10,'15minute': 15, '30minute': 25, '60minute': 40, 'day': 80}
			self.stock_step_df                      = {'NIFTY': 50, 'BANKNIFTY': 100,'FINNIFTY': 50, 'AARTIIND': 5, 'ABB': 50, 'ABBOTINDIA': 250, 'ACC': 20, 'ADANIENT': 50, 'ADANIPORTS': 10, 'ALKEM': 20, 'AMBUJACEM': 10, 'APOLLOHOSP': 50, 'APOLLOTYRE': 5, 'ASHOKLEY': 1, 'ASIANPAINT': 20, 'ASTRAL': 20, 'ATUL': 50, 'AUBANK': 10, 'AUROPHARMA': 10, 'AXISBANK': 10, 'BAJAJ-AUTO': 50, 'BAJAJFINSV': 20, 'BAJFINANCE': 50, 'BALKRISIND': 20, 'BALRAMCHIN': 5, 'BATAINDIA': 10, 'BEL': 1, 'BERGEPAINT': 5, 'BHARATFORG': 10, 'BHARTIARTL': 10, 'BHEL': 1, 'BOSCHLTD': 100, 'BPCL': 5, 'BRITANNIA': 50, 'BSOFT': 10, 'CANBK': 5, 'CANFINHOME': 10, 'CHOLAFIN': 10, 'CIPLA': 10, 'COFORGE': 100, 'COLPAL': 10, 'CONCOR': 10, 'COROMANDEL': 10, 'CUB': 1, 'CUMMINSIND': 20, 'DABUR': 5, 'DALBHARAT': 20, 'DEEPAKNTR': 20, 'DELTACORP': 5, 'DIVISLAB': 50, 'DIXON': 50, 'DLF': 5, 'DRREDDY': 50, 'EICHERMOT': 50, 'ESCORTS': 20, 'FEDERALBNK': 1, 'GAIL': 1, 'GLENMARK': 10, 'GNFC': 10, 'GODREJCP': 10, 'GODREJPROP': 20, 'GRASIM': 20, 'GUJGASLTD': 5, 'HAL': 20, 'HAVELLS': 10, 'HCLTECH': 10, 'HDFCAMC': 20, 'HDFCBANK': 10, 'HDFCLIFE': 5, 'HEROMOTOCO': 20, 'HINDALCO': 5, 'HINDCOPPER': 2.5, 'HINDUNILVR': 20, 'ICICIBANK': 10, 'ICICIGI': 10, 'ICICIPRULI': 5, 'IDEA': 1, 'IDFC': 1, 'IDFCFIRSTB': 1, 'IEX': 1, 'IGL': 5, 'INDHOTEL': 5, 'INDIAMART': 50, 'INDIGO': 20, 'INDUSINDBK': 20, 'INFY': 10, 'IOC': 1, 'IPCALAB': 10, 'IRCTC': 10, 'ITC': 5, 'JINDALSTEL': 10, 'JKCEMENT': 50, 'JSWSTEEL': 10, 'JUBLFOOD': 5, 'KOTAKBANK': 20, 'L&TFH': 1, 'LALPATHLAB': 20, 'LAURUSLABS': 5, 'LICHSGFIN': 5, 'LT': 20, 'LTIM': 50, 'LTTS': 50, 'LUPIN': 10, 'M&M': 10, 'M&MFIN': 5, 'MARICO': 5, 'MARUTI': 100, 'MCDOWELL-N': 10, 'MCX': 20, 'METROPOLIS': 20, 'MFSL': 10, 'MGL': 10, 'MOTHERSON': 1, 'MPHASIS': 20, 'MRF': 500, 'MUTHOOTFIN': 10, 'NATIONALUM': 1, 'NAUKRI': 50, 'NAVINFLUOR': 50, 'NESTLEIND': 100, 'NMDC': 1, 'NTPC': 1, 'OBEROIRLTY': 10, 'OFSS': 20, 'ONGC': 2.5, 'PAGEIND': 500, 'PEL': 10, 'PERSISTENT': 50, 'PIDILITIND': 20, 'PIIND': 50, 'PNB': 1, 'POLYCAB': 50, 'PVRINOX': 20, 'RAMCOCEM': 10, 'RELIANCE': 20, 'SAIL': 1, 'SBICARD': 10, 'SBILIFE': 10, 'SBIN': 10, 'SHREECEM': 250, 'SHRIRAMFIN': 20, 'SIEMENS': 50, 'SRF': 20, 'SUNPHARMA': 10, 'SUNTV': 5, 'SYNGENE': 10, 'TATACHEM': 10, 'TATACOMM': 20, 'TATACONSUM': 5, 'TATAMOTORS': 5, 'TATASTEEL': 1, 'TCS': 20, 'TECHM': 10, 'TITAN': 20, 'TORNTPHARM': 20, 'TRENT': 20, 'TVSMOTOR': 20, 'UBL': 10, 'ULTRACEMCO': 50, 'UPL': 5, 'VOLTAS': 10, 'ZYDUSLIFE': 5, 'ABCAPITAL': 2.5, 'ABFRL': 2.5, 'BANDHANBNK': 2.5, 'BANKBARODA': 2.5, 'BIOCON': 2.5, 'CHAMBLFERT': 5, 'COALINDIA': 2.5, 'CROMPTON': 2.5, 'EXIDEIND': 2.5, 'GRANULES': 2.5, 'HINDPETRO': 5, 'IBULHSGFIN': 2.5, 'INDIACEM': 2.5, 'INDUSTOWER': 2.5, 'MANAPPURAM': 2.5, 'PETRONET': 2.5, 'PFC': 2.5, 'POWERGRID': 2.5, 'RBLBANK': 2.5, 'RECLTD': 2.5, 'TATAPOWER': 5, 'VEDL': 2.5, 'WIPRO': 2.5, 'ZEEL': 2.5, 'AMARAJABAT': 10, 'APLLTD': 10, 'CADILAHC': 5, 'HDFC': 50, 'LTI': 100, 'MINDTREE': 20, 'MOTHERSUMI': 5, 'NAM-INDIA': 5, 'PFIZER': 50, 'PVR': 20, 'SRTRANSFIN': 20, 'TORNTPOWER': 5}
			self.stock_step_df 						= {'SUNTV': 10, 'LTF': 2, 'VEDL': 10, 'SHRIRAMFIN': 10, 'GODREJPROP': 50, 'BHEL': 5, 'ATUL': 100, 'UNITDSPR': 20, 'SBIN': 10, 'PERSISTENT': 100, 'POWERGRID': 5, 'MARICO': 10, 'MOTHERSON': 2, 'HAVELLS': 20, 'BALKRISIND': 20, 'GRASIM': 20, 'MGL': 20, 'INDUSTOWER': 5, 'NATIONALUM': 5, 'DIVISLAB': 50, 'GNFC': 10, 'DLF': 10, 'AMBUJACEM': 5, 'CHOLAFIN': 20, 'IDFCFIRSTB': 1, 'CHAMBLFERT': 10, 'ABFRL': 5, 'CANFINHOME': 10, 'M&MFIN': 5, 'DABUR': 5, 'HINDCOPPER': 5, 'RAMCOCEM': 10, 'M&M': 50, 'NAVINFLUOR': 50, 'EXIDEIND': 5, 'ICICIGI': 20, 'TATAMOTORS': 10, 'GLENMARK': 20, 'POLYCAB': 100, 'CIPLA': 20, 'IOC': 2, 'INDUSINDBK': 10, 'CROMPTON': 5, 'PIDILITIND': 20, 'PIIND': 50, 'IDEA': 1, 'TATACONSUM': 10, 'METROPOLIS': 20, 'TVSMOTOR': 20, 'DEEPAKNTR': 50, 'RELIANCE': 10, 'CONCOR': 10, 'SUNPHARMA': 20, 'PETRONET': 5, 'ONGC': 2, 'ABBOTINDIA': 250, 'BHARTIARTL': 20, 'BEL': 5, 'BRITANNIA': 50, 'AARTIIND': 5, 'RBLBANK': 2, 'EICHERMOT': 50, 'SRF': 20, 'APOLLOHOSP': 50, 'GMRAIRPORT': 1, 'DRREDDY': 10, 'CANBK': 1, 'BPCL': 5, 'PEL': 20, 'ADANIPORTS': 20, 'TECHM': 20, 'ASIANPAINT': 20, 'ALKEM': 50, 'VOLTAS': 20, 'PNB': 1, 'MCX': 100, 'TATACHEM': 20, 'ZYDUSLIFE': 10, 'LICHSGFIN': 10, 'TATASTEEL': 1, 'BSOFT': 10, 'WIPRO': 2, 'SBICARD': 5, 'JUBLFOOD': 10, 'HAL': 50, 'TORNTPHARM': 50, 'CUMMINSIND': 50, 'COLPAL': 20, 'TCS': 50, 'GAIL': 2, 'IEX': 2, 'TITAN': 50, 'COALINDIA': 5, 'HDFCLIFE': 10, 'PFC': 10, 'CUB': 2, 'SHREECEM': 250, 'KOTAKBANK': 20, 'HEROMOTOCO': 50, 'BERGEPAINT': 5, 'SAIL': 2, 'MANAPPURAM': 2, 'SBILIFE': 20, 'SIEMENS': 100, 'NAUKRI': 100, 'LUPIN': 20, 'GRANULES': 10, 'MPHASIS': 50, 'RECLTD': 10, 'BANDHANBNK': 2, 'INDIAMART': 20, 'ICICIPRULI': 10, 'ULTRACEMCO': 100, 'LTIM': 100, 'DALBHARAT': 20, 'HINDUNILVR': 20, 'INDHOTEL': 10, 'MRF': 500, 'ICICIBANK': 10, 'JSWSTEEL': 10, 'ABCAPITAL': 2, 'BHARATFORG': 20, 'PVRINOX': 20, 'NMDC': 1, 'HDFCAMC': 50, 'LT': 50, 'BAJFINANCE': 200, 'INDIGO': 50, 'OFSS': 250, 'COROMANDEL': 20, 'SYNGENE': 10, 'INFY': 20, 'GODREJCP': 10, 'ABB': 100, 'DIXON': 250, 'UPL': 10, 'MARUTI': 100, 'TATACOMM': 20, 'IRCTC': 10, 'OBEROIRLTY': 20, 'BIOCON': 5, 'GUJGASLTD': 5, 'BAJAJFINSV': 20, 'MFSL': 20, 'HINDALCO': 10, 'HDFCBANK': 20, 'BOSCHLTD': 500, 'AUROPHARMA': 20, 'AXISBANK': 10, 'MUTHOOTFIN': 20, 'JKCEMENT': 50, 'TATAPOWER': 5, 'APOLLOTYRE': 10, 'UBL': 20, 'LALPATHLAB': 50, 'IPCALAB': 20, 'FEDERALBNK': 2, 'LAURUSLABS': 10, 'ADANIENT': 40, 'ACC': 20, 'JINDALSTEL': 20, 'COFORGE': 100, 'ASHOKLEY': 2, 'ASTRAL': 20, 'PAGEIND': 500, 'ESCORTS': 50, 'NESTLEIND': 20, 'BANKBARODA': 2, 'HINDPETRO': 5, 'HCLTECH': 20, 'TRENT': 100, 'BATAINDIA': 10, 'LTTS': 50, 'IGL': 2, 'AUBANK': 5, 'NTPC': 5, 'PAYTM': 20, 'TIINDIA': 50, 'OIL': 10, 'JSL': 10, 'ZOMATO': 5, 'JSWENERGY': 10, 'VBL': 10, 'ADANIENSOL': 20, 'CGPOWER': 10, 'SONACOMS': 10, 'JIOFIN': 5, 'NCC': 5, 'UNIONBANK': 1, 'CYIENT': 20, 'YESBANK': 1, 'LICI': 10, 'HFCL': 2, 'BANKINDIA': 1, 'ADANIGREEN': 20, 'IRB': 1, 'NHPC': 1, 'DELHIVERY': 5, 'PRESTIGE': 50, 'ATGL': 10, 'SJVN': 2, 'CESC': 5, 'MAXHEALTH': 20, 'IRFC': 2, 'APLAPOLLO': 20, 'KPITTECH': 20, 'LODHA': 20, 'DMART': 50, 'INDIANB': 10, 'KALYANKJIL': 20, 'POLICYBZR': 50, 'HUDCO': 5, 'ANGELONE': 200, 'NYKAA': 2, 'KEI': 100, 'SUPREMEIND': 100, 'POONAWALLA': 5, 'TATAELXSI': 100, 'CAMS': 100, 'ITC': 5, 'NBCC':2}
			self.commodity_step_dict 				= {'GOLD': 100,'SILVER': 250,'CRUDEOIL': 50,'NATURALGAS': 5,'COPPER': 5,'NICKEL': 10,'ZINC': 2.5,'LEAD': 1, 'ALUMINIUM': 1,    'COTTON': 100,     'MENTHAOIL': 10,   'GOLDM': 50,       'GOLDPETAL': 5,    'GOLDGUINEA': 10,  'SILVERM': 250,     'SILVERMIC': 10,   'BRASS': 5,        'CASTORSEED': 100, 'COTTONSEEDOILCAKE': 50, 'CARDAMOM': 50,    'RBDPALMOLEIN': 10,'CRUDEPALMOIL': 10,'PEPPER': 100,     'JEERA': 100,      'SOYABEAN': 50,    'SOYAOIL': 10,     'TURMERIC': 100,   'GUARGUM': 100,    'GUARSEED': 100,   'CHANA': 50,       'MUSTARDSEED': 50, 'BARLEY': 50,      'SUGARM': 50,      'WHEAT': 50,       'MAIZE': 50,       'PADDY': 50,       'BAJRA': 50,       'JUTE': 50,        'RUBBER': 100,     'COFFEE': 50,      'COPRA': 50,       'SESAMESEED': 50,  'TEA': 100,        'KAPAS': 100,      'BARLEYFEED': 50,  'RAPESEED': 50,    'LINSEED': 50,     'SUNFLOWER': 50,   'CORIANDER': 50,   'CUMINSEED': 100   }
			self.start_date, self.end_date          = self.get_start_date()
			self.correct_list  						= {'SUNTV': 10, 'LTF': 2, 'VEDL': 10, 'SHRIRAMFIN': 10, 'GODREJPROP': 50, 'BHEL': 5, 'ATUL': 100, 'UNITDSPR': 20, 'SBIN': 10, 'PERSISTENT': 100, 'POWERGRID': 5, 'MARICO': 10, 'MOTHERSON': 2, 'HAVELLS': 20, 'BALKRISIND': 20, 'GRASIM': 20, 'MGL': 20, 'INDUSTOWER': 5, 'NATIONALUM': 5, 'DIVISLAB': 50, 'GNFC': 10, 'DLF': 10, 'AMBUJACEM': 5, 'CHOLAFIN': 20, 'IDFCFIRSTB': 1, 'CHAMBLFERT': 10, 'ABFRL': 5, 'CANFINHOME': 10, 'M&MFIN': 5, 'DABUR': 5, 'HINDCOPPER': 5, 'RAMCOCEM': 10, 'M&M': 50, 'NAVINFLUOR': 50, 'EXIDEIND': 5, 'ICICIGI': 20, 'TATAMOTORS': 10, 'GLENMARK': 20, 'POLYCAB': 100, 'CIPLA': 20, 'IOC': 2, 'INDUSINDBK': 10, 'CROMPTON': 5, 'PIDILITIND': 20, 'PIIND': 50, 'IDEA': 1, 'TATACONSUM': 10, 'METROPOLIS': 20, 'TVSMOTOR': 20, 'DEEPAKNTR': 50, 'RELIANCE': 10, 'CONCOR': 10, 'SUNPHARMA': 20, 'PETRONET': 5, 'ONGC': 2, 'ABBOTINDIA': 250, 'BHARTIARTL': 20, 'BEL': 5, 'BRITANNIA': 50, 'AARTIIND': 5, 'RBLBANK': 2, 'EICHERMOT': 50, 'SRF': 20, 'APOLLOHOSP': 50, 'GMRAIRPORT': 1, 'DRREDDY': 10, 'CANBK': 1, 'BPCL': 5, 'PEL': 20, 'ADANIPORTS': 20, 'TECHM': 20, 'ASIANPAINT': 20, 'ALKEM': 50, 'VOLTAS': 20, 'PNB': 1, 'MCX': 100, 'TATACHEM': 20, 'ZYDUSLIFE': 10, 'LICHSGFIN': 10, 'TATASTEEL': 1, 'BSOFT': 10, 'WIPRO': 2, 'SBICARD': 5, 'JUBLFOOD': 10, 'HAL': 50, 'TORNTPHARM': 50, 'CUMMINSIND': 50, 'COLPAL': 20, 'TCS': 50, 'GAIL': 2, 'IEX': 2, 'TITAN': 50, 'COALINDIA': 5, 'HDFCLIFE': 10, 'PFC': 10, 'CUB': 2, 'SHREECEM': 250, 'KOTAKBANK': 20, 'HEROMOTOCO': 50, 'BERGEPAINT': 5, 'SAIL': 2, 'MANAPPURAM': 2, 'SBILIFE': 20, 'SIEMENS': 100, 'NAUKRI': 100, 'LUPIN': 20, 'GRANULES': 10, 'MPHASIS': 50, 'RECLTD': 10, 'BANDHANBNK': 2, 'INDIAMART': 20, 'ICICIPRULI': 10, 'ULTRACEMCO': 100, 'LTIM': 100, 'DALBHARAT': 20, 'HINDUNILVR': 20, 'INDHOTEL': 10, 'MRF': 500, 'ICICIBANK': 10, 'JSWSTEEL': 10, 'ABCAPITAL': 2, 'BHARATFORG': 20, 'PVRINOX': 20, 'NMDC': 1, 'HDFCAMC': 50, 'LT': 50, 'BAJFINANCE': 200, 'INDIGO': 50, 'OFSS': 250, 'COROMANDEL': 20, 'SYNGENE': 10, 'INFY': 20, 'GODREJCP': 10, 'ABB': 100, 'DIXON': 250, 'UPL': 10, 'MARUTI': 100, 'TATACOMM': 20, 'IRCTC': 10, 'OBEROIRLTY': 20, 'BIOCON': 5, 'GUJGASLTD': 5, 'BAJAJFINSV': 20, 'MFSL': 20, 'HINDALCO': 10, 'HDFCBANK': 20, 'BOSCHLTD': 500, 'AUROPHARMA': 20, 'AXISBANK': 10, 'MUTHOOTFIN': 20, 'JKCEMENT': 50, 'TATAPOWER': 5, 'APOLLOTYRE': 10, 'UBL': 20, 'LALPATHLAB': 50, 'IPCALAB': 20, 'FEDERALBNK': 2, 'LAURUSLABS': 10, 'ADANIENT': 40, 'ACC': 20, 'JINDALSTEL': 20, 'COFORGE': 100, 'ASHOKLEY': 2, 'ASTRAL': 20, 'PAGEIND': 500, 'ESCORTS': 50, 'NESTLEIND': 20, 'BANKBARODA': 2, 'HINDPETRO': 5, 'HCLTECH': 20, 'TRENT': 100, 'BATAINDIA': 10, 'LTTS': 50, 'IGL': 2, 'AUBANK': 5, 'NTPC': 5, 'PAYTM': 20, 'TIINDIA': 50, 'OIL': 10, 'JSL': 10, 'ZOMATO': 5, 'JSWENERGY': 10, 'VBL': 10, 'ADANIENSOL': 20, 'CGPOWER': 10, 'SONACOMS': 10, 'JIOFIN': 5, 'NCC': 5, 'UNIONBANK': 1, 'CYIENT': 20, 'YESBANK': 1, 'LICI': 10, 'HFCL': 2, 'BANKINDIA': 1, 'ADANIGREEN': 20, 'IRB': 1, 'NHPC': 1, 'DELHIVERY': 5, 'PRESTIGE': 50, 'ATGL': 10, 'SJVN': 2, 'CESC': 5, 'MAXHEALTH': 20, 'IRFC': 2, 'APLAPOLLO': 20, 'KPITTECH': 20, 'LODHA': 20, 'DMART': 50, 'INDIANB': 10, 'KALYANKJIL': 20, 'POLICYBZR': 50, 'HUDCO': 5, 'ANGELONE': 200, 'NYKAA': 2, 'KEI': 100, 'SUPREMEIND': 100, 'POONAWALLA': 5, 'TATAELXSI': 100, 'CAMS': 100, 'ITC': 5, 'NBCC':2}
			# self.correct_list                       = {'AARTIIND': 10, 'ABB': 100, 'ABBOTINDIA': 250, 'ACC': 20, 'ADANIENT': 20, 'ADANIPORTS': 20, 'ALKEM': 100, 'AMBUJACEM': 10, 'APOLLOHOSP': 50, 'APOLLOTYRE': 10, 'ASIANPAINT': 20, 'ASTRAL': 20, 'ATUL': 100, 'AUBANK': 10, 'AUROPHARMA': 20, 'AXISBANK': 10, 'BAJAJ-AUTO': 100, 'BAJAJFINSV': 20, 'BAJFINANCE': 100, 'BALKRISIND': 50, 'BATAINDIA': 10, 'BEL': 5, 'BERGEPAINT': 5, 'BHARATFORG': 20, 'BHARTIARTL': 40, 'BHEL': 10, 'BOSCHLTD': 500, 'BPCL': 5, 'BRITANNIA': 50, 'BSOFT': 10, 'CANBK': 2, 'CANFINHOME': 20, 'CHOLAFIN': 40, 'CIPLA': 20, 'COFORGE': 100, 'COLPAL': 50, 'CONCOR': 10, 'COROMANDEL': 20, 'CUB': 2, 'CUMMINSIND': 50, 'DABUR': 5, 'DALBHARAT': 20, 'DEEPAKNTR': 50, 'DIVISLAB': 50, 'DLF': 10, 'DRREDDY': 10, 'EICHERMOT': 50, 'ESCORTS': 50, 'FEDERALBNK': 2, 'GAIL': 2, 'GLENMARK': 20, 'GNFC': 10, 'GODREJCP': 20, 'GODREJPROP': 50, 'GRASIM': 20, 'GUJGASLTD': 10, 'HAL': 100, 'HAVELLS': 20, 'HCLTECH': 20, 'HDFCAMC': 50, 'HDFCBANK': 10, 'HDFCLIFE': 10, 'HEROMOTOCO': 100, 'HINDALCO': 10, 'HINDCOPPER': 5, 'HINDUNILVR': 20, 'ICICIBANK': 10, 'ICICIGI': 20, 'ICICIPRULI': 10, 'IDEA': 1, 'IDFCFIRSTB': 1, 'IEX': 2, 'IGL': 10, 'INDHOTEL': 10, 'INDIAMART': 50, 'INDIGO': 50, 'INDUSINDBK': 20, 'INFY': 20, 'IOC': 2, 'IPCALAB': 20, 'IRCTC': 10, 'ITC': 5, 'JINDALSTEL': 10, 'JKCEMENT': 50, 'JSWSTEEL': 10, 'JUBLFOOD': 10, 'KOTAKBANK': 20, 'LALPATHLAB': 50, 'LAURUSLABS': 10, 'LICHSGFIN': 10, 'LTIM': 50, 'LTTS': 50, 'LUPIN': 20, 'M&M': 50, 'MARICO': 10, 'MARUTI': 100, 'MCX': 100, 'METROPOLIS': 20, 'MFSL': 20, 'MGL': 20, 'MOTHERSON': 2, 'MPHASIS': 50, 'MRF': 500, 'MUTHOOTFIN': 20, 'NATIONALUM': 2, 'NAUKRI': 100, 'NAVINFLUOR': 50, 'NESTLEIND': 20, 'NMDC': 5, 'NTPC': 5, 'OBEROIRLTY': 20, 'OFSS': 250, 'ONGC': 5, 'PAGEIND': 500, 'PEL': 20, 'PERSISTENT': 100, 'PIDILITIND': 20, 'PIIND': 50, 'PNB': 1, 'POLYCAB': 100, 'PVRINOX': 20, 'RAMCOCEM': 10, 'RELIANCE': 10, 'SBICARD': 5, 'SBILIFE': 20, 'SBIN': 10, 'SHREECEM': 250, 'SHRIRAMFIN': 50, 'SIEMENS': 100, 'SRF': 20, 'SUNPHARMA': 20, 'SUNTV': 10, 'SYNGENE': 10, 'TATACHEM': 20, 'TATACOMM': 20, 'TATACONSUM': 10, 'TATAMOTORS': 10, 'TATASTEEL': 2, 'TCS': 50, 'TECHM': 20, 'TORNTPHARM': 50, 'TRENT': 100, 'TVSMOTOR': 50, 'UBL': 20, 'ULTRACEMCO': 100, 'UPL': 10, 'VOLTAS': 20, 'ZYDUSLIFE': 20, 'ABFRL': 5, 'BANDHANBNK': 2, 'BIOCON': 5, 'CHAMBLFERT': 10, 'CROMPTON': 5, 'EXIDEIND': 10, 'GRANULES': 10, 'HINDPETRO': 5, 'INDUSTOWER': 10, 'PETRONET': 5, 'PFC': 10, 'POWERGRID': 5, 'RECLTD': 10, 'TATAPOWER': 5, 'VEDL': 10, 'WIPRO': 2}
			# self.correct_step_df_creation()
		except Exception as e:
			print(e)
			traceback.print_exc()


	def _setup_logger(self, enable_file_logging: bool = False):
		logger_name = f"Dhansrp.{id(self)}"
		logger = logging.getLogger(logger_name)
		logger.setLevel(logging.DEBUG)
		logger.propagate = False
		if logger.handlers:
			return logger

		formatter = logging.Formatter('%(levelname)s:%(asctime)s:%(threadName)-10s:%(message)s')
		stream_handler = logging.StreamHandler()
		stream_handler.setFormatter(formatter)
		logger.addHandler(stream_handler)

		if enable_file_logging:
			date_str = str(datetime.datetime.now().today().date())
			log_dir = Path(__file__).resolve().parent / 'Dependencies' / 'log_files'
			log_dir.mkdir(parents=True, exist_ok=True)
			file_handler = logging.FileHandler(log_dir / f'logs{date_str}.log')
			file_handler.setFormatter(formatter)
			logger.addHandler(file_handler)

		return logger

	def _load_config(self, path: str) -> dict:
		with open(path, encoding='utf-8') as handle:
			return json.load(handle)

	def _resolve_credentials(self, ClientCode=None, token_id=None, config_path=None):
		client_code = ClientCode or os.environ.get('DHAN_CLIENT_ID')
		access_token = token_id or os.environ.get('DHAN_ACCESS_TOKEN')
		paths_to_try = [config_path, self.config_path, os.environ.get('DHAN_CONFIG_PATH'), 'config.json']

		for path in paths_to_try:
			if not path or not os.path.exists(path):
				continue
			config = self._load_config(path)
			client_code = client_code or config.get('client_id') or config.get('ClientCode')
			access_token = access_token or config.get('access_token') or config.get('token_id')
			if client_code and access_token:
				break

		if not client_code or not access_token:
			raise ValueError('Credentials not found. Pass ClientCode/token_id, set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN, or provide config_path.')

		return str(client_code), str(access_token)

	def _build_client(self, client_code: str, access_token: str):
		if DhanContext is not None:
			try:
				self.dhan_context = DhanContext(client_code, access_token)
				return dhanhq(self.dhan_context)
			except TypeError:
				self.dhan_context = None
		self.dhan_context = None
		return dhanhq(client_code, access_token)

	def get_login(self,ClientCode,token_id):
		try:
			self.ClientCode, self.token_id = self._resolve_credentials(ClientCode, token_id, self.config_path)
			print("-----Logged into Dhan-----")
			self.Dhan = self._build_client(self.ClientCode, self.token_id)
			self.instrument_df = self.get_instrument_file()
			print('Got the instrument file')
		except Exception as e:
			print(e)
			self.logger.exception(f'got exception in get_login as {e} ')
			traceback.print_exc()

	def _normalize_instrument_df(self, instrument_df: pd.DataFrame):
		instrument_df = instrument_df.copy()
		if 'SEM_CUSTOM_SYMBOL' in instrument_df.columns:
			instrument_df['SEM_CUSTOM_SYMBOL'] = instrument_df['SEM_CUSTOM_SYMBOL'].astype(str).str.strip().str.replace(r'\s+', ' ', regex=True)
		if 'SEM_TRADING_SYMBOL' in instrument_df.columns:
			instrument_df['SEM_TRADING_SYMBOL'] = instrument_df['SEM_TRADING_SYMBOL'].astype(str).str.strip()
		return instrument_df

	def get_instrument_file(self):
		global instrument_df
		expected_file = 'all_instrument.csv'
		expected_path = None
		if self.instrument_cache_path:
			expected_path = Path(self.instrument_cache_path)
		elif self.persist_instrument_file:
			dependencies_dir = Path(__file__).resolve().parent / 'Dependencies'
			dependencies_dir.mkdir(parents=True, exist_ok=True)
			expected_path = dependencies_dir / expected_file

		if expected_path and expected_path.exists():
			try:
				print(f"reading existing file {expected_path.name}")
				instrument_df = pd.read_csv(expected_path, low_memory=False)
				return self._normalize_instrument_df(instrument_df)
			except Exception:
				self.logger.warning('Instrument cache read failed. Fetching a fresh security master.')

		print('Fetching security master from Dhan')
		if hasattr(dhanhq, 'fetch_security_list'):
			try:
				instrument_df = dhanhq.fetch_security_list('compact')
			except TypeError:
				instrument_df = dhanhq.fetch_security_list()
		else:
			instrument_df = pd.read_csv('https://images.dhan.co/api-data/api-scrip-master.csv', low_memory=False)

		instrument_df = self._normalize_instrument_df(instrument_df)
		if expected_path is not None:
			try:
				instrument_df.to_csv(expected_path, index=False)
			except Exception as e:
				self.logger.warning(f'Unable to persist instrument file: {e}')
		return instrument_df

	def unwrap_sdk_data(self, response: dict):
		if response.get('status') != 'success':
			raise ValueError(response.get('remarks') or response)
		return response.get('data')

	def get_security_master(self, refresh: bool = False):
		if refresh or getattr(self, 'instrument_df', None) is None or self.instrument_df.empty:
			self.instrument_df = self.get_instrument_file()
		return self.instrument_df.copy()

	def resolve_symbol(self, symbol: str, exchange_segment: str = 'NSE_EQ', instrument_name: str = 'EQUITY'):
		df = self.get_security_master()
		query = symbol.upper().strip()
		exchange = exchange_segment.split('_')[0].replace('EQ', '').replace('FNO', '').replace('CURRENCY', '')
		exchange = 'NSE' if exchange == 'NSE' else ('BSE' if exchange == 'BSE' else ('MCX' if exchange == 'MCX' else exchange))
		exact = df[(df['SEM_EXM_EXCH_ID'].astype(str).str.upper() == exchange) & (df['SEM_INSTRUMENT_NAME'].astype(str).str.upper() == instrument_name.upper()) & (df['SEM_TRADING_SYMBOL'].astype(str).str.upper() == query)]
		if exact.empty:
			exact = df[(df['SEM_EXM_EXCH_ID'].astype(str).str.upper() == exchange) & (df['SEM_INSTRUMENT_NAME'].astype(str).str.upper() == instrument_name.upper()) & (df['SEM_CUSTOM_SYMBOL'].astype(str).str.upper().str.contains(query, na=False))]
		if exact.empty:
			return None
		row = exact.iloc[0]
		return {'security_id': str(row['SEM_SMST_SECURITY_ID']), 'trading_symbol': str(row['SEM_TRADING_SYMBOL']), 'display_name': str(row.get('SEM_CUSTOM_SYMBOL', '')), 'exchange_segment': exchange_segment, 'instrument_name': str(row['SEM_INSTRUMENT_NAME'])}

	def get_security_id_by_symbol(self, symbol: str) -> int:
		query = symbol.upper().strip()
		security_id = NIFTY50_SECURITY_IDS.get(query)
		if security_id is None:
			raise ValueError(f"Security ID not found for symbol: {symbol}")
		return int(security_id)

	def resolve_derivative(self, underlying: str, instrument_names: tuple = ('OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK'), strike: float = None, option_type: str = None, expiry: str = None, exchange: str = 'NSE'):
		df = self.get_security_master()
		mask = ((df['SEM_EXM_EXCH_ID'].astype(str).str.upper() == exchange.upper()) & (df['SEM_INSTRUMENT_NAME'].isin(instrument_names)) & (df['SEM_CUSTOM_SYMBOL'].astype(str).str.upper() == underlying.upper()))
		if strike is not None:
			mask &= df['SEM_STRIKE_PRICE'].astype(float) == float(strike)
		if option_type is not None:
			mask &= df['SEM_OPTION_TYPE'].astype(str).str.upper() == option_type.upper()
		if expiry is not None:
			mask &= df['SEM_EXPIRY_DATE'].astype(str) == expiry
		matches = df[mask].sort_values(['SEM_EXPIRY_DATE', 'SEM_TRADING_SYMBOL'])
		if matches.empty:
			return None
		row = matches.iloc[0]
		return {'security_id': str(row['SEM_SMST_SECURITY_ID']), 'trading_symbol': str(row['SEM_TRADING_SYMBOL']), 'lot_size': int(row['SEM_LOT_UNITS']) if not pd.isna(row.get('SEM_LOT_UNITS')) else None, 'tick_size': float(row['SEM_TICK_SIZE']) if not pd.isna(row.get('SEM_TICK_SIZE')) else None, 'expiry': str(row.get('SEM_EXPIRY_DATE', '')), 'instrument_name': str(row['SEM_INSTRUMENT_NAME'])}

	def get_lot_size_from_master(self, security_id: str = None, trading_symbol: str = None, underlying: str = None):
		df = self.get_security_master()
		if security_id is not None:
			match = df[df['SEM_SMST_SECURITY_ID'].astype(str) == str(security_id)]
			if not match.empty:
				return int(match.iloc[0]['SEM_LOT_UNITS'])
		if trading_symbol is not None:
			match = df[df['SEM_TRADING_SYMBOL'].astype(str).str.upper() == trading_symbol.upper()]
			if not match.empty:
				return int(match.iloc[0]['SEM_LOT_UNITS'])
		if underlying is not None:
			match = df[(df['SEM_CUSTOM_SYMBOL'].astype(str).str.upper() == underlying.upper()) & (df['SEM_INSTRUMENT_NAME'].isin(['OPTIDX', 'OPTSTK', 'FUTIDX', 'FUTSTK']))]
			if not match.empty:
				return int(match.iloc[0]['SEM_LOT_UNITS'])
		return None

	def preview_order(self, security_id: str, exchange_segment: str, transaction_type: str, quantity: int, order_type: str, product_type: str, price: float = 0.0, trading_symbol: str = None):
		notional = price * quantity if price else 0
		lines = ['--- ORDER PREVIEW ---', f"Security:     {trading_symbol or security_id}", f"Exchange:     {exchange_segment}", f"Action:       {transaction_type}", f"Quantity:     {quantity}", f"Order Type:   {order_type}", f"Product Type: {product_type}", f"Price:        {'MARKET / MPP' if order_type == 'MARKET' else f'Rs. {price:,.2f}'}"]
		if notional:
			lines.append(f"Notional:     Rs. {notional:,.2f}")
		if notional > 50000:
			lines.append('Warning:      Notional exceeds Rs. 50,000')
		lines.append('---------------------')
		return '\n'.join(lines)

	def validate_order_payload(self, security_id: str = None, exchange_segment: str = None, transaction_type: str = None, quantity: int = None, order_type: str = None, product_type: str = None, price: float = 0, trigger_price: float = 0, validity: str = 'DAY', after_market_order: bool = False, trading_symbol: str = None, lot_size: int = None):
		errors = []
		warnings_list = []
		valid_exchange_segments = {'NSE_EQ', 'BSE_EQ', 'NSE_FNO', 'BSE_FNO', 'MCX_COMM', 'NSE_CURRENCY', 'BSE_CURRENCY'}
		equity_segments = {'NSE_EQ', 'BSE_EQ'}
		derivative_segments = {'NSE_FNO', 'BSE_FNO', 'MCX_COMM', 'NSE_CURRENCY', 'BSE_CURRENCY'}
		equity_product_types = {'CNC', 'INTRADAY', 'MARGIN', 'MTF'}
		derivative_product_types = {'INTRADAY', 'MARGIN'}
		valid_order_types = {'LIMIT', 'MARKET', 'STOP_LOSS', 'STOP_LOSS_MARKET'}
		valid_transaction_types = {'BUY', 'SELL'}
		valid_validity = {'DAY', 'IOC'}
		exchange_segment = exchange_segment.upper() if exchange_segment else exchange_segment
		transaction_type = transaction_type.upper() if transaction_type else transaction_type
		order_type = order_type.upper() if order_type else order_type
		product_type = product_type.upper() if product_type else product_type
		validity = validity.upper() if validity else validity
		if not security_id:
			errors.append('security_id is required')
		if not exchange_segment:
			errors.append('exchange_segment is required')
		if not transaction_type:
			errors.append('transaction_type is required')
		if quantity is None or quantity <= 0:
			errors.append('quantity must be a positive integer')
		if not order_type:
			errors.append('order_type is required')
		if not product_type:
			errors.append('product_type is required')
		if exchange_segment and exchange_segment not in valid_exchange_segments:
			errors.append(f'Invalid exchange_segment: {exchange_segment}')
		if transaction_type and transaction_type not in valid_transaction_types:
			errors.append(f'Invalid transaction_type: {transaction_type}')
		if order_type and order_type not in valid_order_types:
			errors.append(f'Invalid order_type: {order_type}')
		if validity and validity not in valid_validity:
			errors.append(f'Invalid validity: {validity}')
		if order_type in {'LIMIT', 'STOP_LOSS'} and price <= 0:
			errors.append(f'price is required for {order_type} orders')
		if order_type in {'STOP_LOSS', 'STOP_LOSS_MARKET'} and trigger_price <= 0:
			errors.append(f'trigger_price is required for {order_type} orders')
		if exchange_segment in equity_segments and product_type and product_type not in equity_product_types:
			errors.append(f"Invalid product_type '{product_type}' for equity segment '{exchange_segment}'.")
		if exchange_segment in derivative_segments and product_type and product_type not in derivative_product_types:
			errors.append(f"Invalid product_type '{product_type}' for derivative segment '{exchange_segment}'.")
		effective_lot_size = lot_size or self.get_lot_size_from_master(security_id=security_id, trading_symbol=trading_symbol)
		if exchange_segment in derivative_segments and quantity:
			if effective_lot_size is not None and quantity % effective_lot_size != 0:
				errors.append(f'Derivative quantity must be a multiple of lot size {effective_lot_size}. Got {quantity}.')
			elif effective_lot_size is None:
				warnings_list.append('Could not resolve a lot size from the security master. Confirm the lot size before placing.')
		if price and quantity and (price * quantity) > 50000:
			warnings_list.append(f'High notional value: Rs. {price * quantity:,.2f} exceeds the Rs. 50,000 warning threshold.')
		if order_type == 'MARKET':
			warnings_list.append("Dhan API market orders may be converted to limit orders with MPP.")
		if not after_market_order and datetime.datetime.now().weekday() >= 5:
			warnings_list.append('Market is closed on weekends. Use AMO only if that is intentional.')
		return {'valid': not errors, 'errors': errors, 'warnings': warnings_list}

	def _sdk_exchange_segment(self, exchange_segment: str):
		segment = exchange_segment.upper()
		mapping = {
			'NSE_EQ': getattr(self.Dhan, 'NSE', 'NSE_EQ'),
			'BSE_EQ': getattr(self.Dhan, 'BSE', 'BSE_EQ'),
			'NSE_FNO': getattr(self.Dhan, 'FNO', getattr(self.Dhan, 'NSE_FNO', 'NSE_FNO')),
			'BSE_FNO': getattr(self.Dhan, 'BSE_FNO', 'BSE_FNO'),
			'MCX_COMM': getattr(self.Dhan, 'MCX', 'MCX_COMM'),
			'NSE_CURRENCY': getattr(self.Dhan, 'CUR', 'NSE_CURRENCY'),
			'BSE_CURRENCY': getattr(self.Dhan, 'BSE_CURRENCY', 'BSE_CURRENCY'),
			'IDX_I': getattr(self.Dhan, 'INDEX', 'IDX_I'),
		}
		if segment not in mapping:
			raise ValueError(f'Unsupported exchange_segment: {exchange_segment}')
		return mapping[segment]

	def _sdk_transaction_type(self, transaction_type: str):
		mapping = {
			'BUY': getattr(self.Dhan, 'BUY', 'BUY'),
			'SELL': getattr(self.Dhan, 'SELL', 'SELL'),
		}
		key = transaction_type.upper()
		if key not in mapping:
			raise ValueError(f'Unsupported transaction_type: {transaction_type}')
		return mapping[key]

	def _sdk_order_type(self, order_type: str):
		mapping = {
			'LIMIT': getattr(self.Dhan, 'LIMIT', 'LIMIT'),
			'MARKET': getattr(self.Dhan, 'MARKET', 'MARKET'),
			'STOP_LOSS': getattr(self.Dhan, 'SL', 'STOP_LOSS'),
			'STOP_LOSS_MARKET': getattr(self.Dhan, 'SLM', 'STOP_LOSS_MARKET'),
			'STOPLIMIT': getattr(self.Dhan, 'SL', 'STOP_LOSS'),
			'STOPMARKET': getattr(self.Dhan, 'SLM', 'STOP_LOSS_MARKET'),
		}
		key = order_type.upper()
		if key not in mapping:
			raise ValueError(f'Unsupported order_type: {order_type}')
		return mapping[key]

	def _sdk_product_type(self, product_type: str):
		mapping = {
			'CNC': getattr(self.Dhan, 'CNC', 'CNC'),
			'INTRADAY': getattr(self.Dhan, 'INTRA', 'INTRADAY'),
			'MIS': getattr(self.Dhan, 'INTRA', 'INTRADAY'),
			'MARGIN': getattr(self.Dhan, 'MARGIN', 'MARGIN'),
			'MTF': getattr(self.Dhan, 'MTF', 'MTF'),
		}
		key = product_type.upper()
		if key not in mapping:
			raise ValueError(f'Unsupported product_type: {product_type}')
		return mapping[key]

	def _sdk_validity(self, validity: str):
		mapping = {
			'DAY': getattr(self.Dhan, 'DAY', 'DAY'),
			'IOC': getattr(self.Dhan, 'IOC', 'IOC'),
		}
		key = validity.upper()
		if key not in mapping:
			raise ValueError(f'Unsupported validity: {validity}')
		return mapping[key]

	def _resolve_order_security(self, symbol: str = None, security_id: str = None, exchange_segment: str = None, instrument_name: str = 'EQUITY'):
		if security_id is not None:
			return {'security_id': str(security_id), 'trading_symbol': symbol or str(security_id), 'exchange_segment': exchange_segment, 'instrument_name': instrument_name}
		if not symbol:
			raise ValueError('Either symbol or security_id is required')
		resolved = self.resolve_symbol(symbol, exchange_segment=exchange_segment, instrument_name=instrument_name)
		if resolved is None:
			raise ValueError(f'Unable to resolve symbol {symbol} for {exchange_segment}')
		return resolved

	def place_order(self, symbol: str = None, security_id: str = None, exchange_segment: str = 'NSE_EQ', transaction_type: str = 'BUY', quantity: int = 1, order_type: str = 'LIMIT', product_type: str = 'CNC', price: float = 0, trigger_price: float = 0, validity: str = 'DAY', disclosed_quantity: int = 0, after_market_order: bool = False, amo_time: str = 'OPEN', tag: str = None, lot_size: int = None, instrument_name: str = 'EQUITY', dry_run: bool = False):
		resolved = self._resolve_order_security(symbol=symbol, security_id=security_id, exchange_segment=exchange_segment, instrument_name=instrument_name)
		validation = self.validate_order_payload(security_id=resolved['security_id'], exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, order_type=order_type, product_type=product_type, price=price, trigger_price=trigger_price, validity=validity, after_market_order=after_market_order, trading_symbol=resolved.get('trading_symbol'), lot_size=lot_size)
		preview = self.preview_order(security_id=resolved['security_id'], exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, order_type=order_type.upper(), product_type=product_type.upper(), price=price, trading_symbol=resolved.get('trading_symbol'))
		if not validation['valid'] or dry_run:
			return {'status': 'validation' if validation['valid'] else 'failure', 'instrument': resolved, 'preview': preview, 'validation': validation}
		payload = {
			'security_id': resolved['security_id'],
			'exchange_segment': self._sdk_exchange_segment(exchange_segment),
			'transaction_type': self._sdk_transaction_type(transaction_type),
			'quantity': int(quantity),
			'order_type': self._sdk_order_type(order_type),
			'product_type': self._sdk_product_type(product_type),
			'price': float(price),
			'trigger_price': float(trigger_price),
			'disclosed_quantity': int(disclosed_quantity),
			'after_market_order': after_market_order,
			'validity': self._sdk_validity(validity),
			'amo_time': amo_time,
		}
		if tag is not None:
			payload['tag'] = tag
		response = self.Dhan.place_order(**payload)
		return {'instrument': resolved, 'preview': preview, 'validation': validation, 'response': response}

	def modify_order_request(self, order_id: str, order_type: str, quantity: int, price: float = 0, trigger_price: float = 0, disclosed_quantity: int = 0, validity: str = 'DAY', leg_name: str = None):
		payload = {
			'order_id': order_id,
			'order_type': self._sdk_order_type(order_type),
			'quantity': int(quantity),
			'price': float(price),
			'trigger_price': float(trigger_price),
			'disclosed_quantity': int(disclosed_quantity),
			'validity': self._sdk_validity(validity),
		}
		if leg_name is not None:
			payload['leg_name'] = leg_name
		return self.Dhan.modify_order(**payload)

	def cancel_order_request(self, order_id: str):
		return self.Dhan.cancel_order(order_id=order_id)

	def get_order_by_id_v2(self, order_id: str):
		return self.Dhan.get_order_by_id(order_id=order_id)

	def get_order_by_correlation_id(self, correlation_id: str):
		return self.Dhan.get_order_by_correlationID(correlation_id)

	def get_order_list_v2(self):
		return self.Dhan.get_order_list()

	def get_trade_book_v2(self):
		return self.Dhan.get_trade_book()

	def place_stock_order(self, symbol: str, quantity: int, transaction_type: str = 'BUY', order_type: str = 'LIMIT', product_type: str = 'INTRADAY', price: float = 0, trigger_price: float = 0, exchange_segment: str = 'NSE_EQ', validity: str = 'DAY', dry_run: bool = False):
		return self.place_order(symbol=symbol, exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, order_type=order_type, product_type=product_type, price=price, trigger_price=trigger_price, validity=validity, instrument_name='EQUITY', dry_run=dry_run)

	def place_option_order(self, underlying: str, expiry: str, strike: float, option_type: str, quantity: int = None, transaction_type: str = 'BUY', order_type: str = 'LIMIT', product_type: str = 'INTRADAY', price: float = 0, trigger_price: float = 0, exchange: str = 'NSE', validity: str = 'DAY', dry_run: bool = False):
		contract = self.resolve_derivative(underlying=underlying, instrument_names=('OPTIDX', 'OPTSTK'), strike=strike, option_type=option_type, expiry=expiry, exchange=exchange)
		if contract is None:
			raise ValueError(f'Unable to resolve option contract for {underlying} {strike} {option_type} {expiry}')
		effective_qty = quantity or contract.get('lot_size') or 1
		exchange_segment = 'NSE_FNO' if exchange.upper() == 'NSE' else 'BSE_FNO'
		return self.place_order(symbol=contract['trading_symbol'], security_id=contract['security_id'], exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=effective_qty, order_type=order_type, product_type=product_type, price=price, trigger_price=trigger_price, validity=validity, lot_size=contract.get('lot_size'), instrument_name=contract.get('instrument_name', 'OPTIDX'), dry_run=dry_run)

	def place_atm_straddle(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', quantity: int = None, transaction_type: str = 'BUY', dry_run: bool = True):
		atm_pair = self.get_atm_option_pair(underlying=underlying, under_security_id=under_security_id, expiry=expiry)
		effective_qty = quantity or atm_pair.get('lot_size') or 1
		call_order = self.place_order(security_id=atm_pair['call_security_id'], symbol=f"{underlying} {int(atm_pair['strike'])} CE", exchange_segment='NSE_FNO', transaction_type=transaction_type, quantity=effective_qty, order_type=order_type, product_type=product_type, price=atm_pair['call_price'], lot_size=atm_pair.get('lot_size'), instrument_name='OPTIDX', dry_run=dry_run)
		put_order = self.place_order(security_id=atm_pair['put_security_id'], symbol=f"{underlying} {int(atm_pair['strike'])} PE", exchange_segment='NSE_FNO', transaction_type=transaction_type, quantity=effective_qty, order_type=order_type, product_type=product_type, price=atm_pair['put_price'], lot_size=atm_pair.get('lot_size'), instrument_name='OPTIDX', dry_run=dry_run)
		return {'strategy': 'ATM_STRADDLE', 'atm_pair': atm_pair, 'call_order': call_order, 'put_order': put_order}

	def place_strangle(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, call_offset: int = 1, put_offset: int = 1, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', quantity: int = None, transaction_type: str = 'BUY', dry_run: bool = True):
		if expiry is None:
			expiry = self.get_expiry_dates(under_security_id)[0]
		chain_df, spot = self.fetch_option_chain_df(under_security_id=under_security_id, expiry=expiry)
		strikes = sorted(chain_df['strike'].tolist())
		atm = self.find_atm_row(chain_df, spot)
		atm_index = strikes.index(float(atm['strike']))
		call_index = min(len(strikes) - 1, atm_index + max(1, int(call_offset)))
		put_index = max(0, atm_index - max(1, int(put_offset)))
		call_strike = strikes[call_index]
		put_strike = strikes[put_index]
		call_row = chain_df[chain_df['strike'] == call_strike].iloc[0]
		put_row = chain_df[chain_df['strike'] == put_strike].iloc[0]
		lot_size = quantity or self.get_lot_size_from_master(underlying=underlying) or 1
		call_order = self.place_order(security_id=call_row['ce_security_id'], symbol=f"{underlying} {int(call_strike)} CE", exchange_segment='NSE_FNO', transaction_type=transaction_type, quantity=lot_size, order_type=order_type, product_type=product_type, price=float(call_row['ce_ltp']), lot_size=lot_size, instrument_name='OPTIDX', dry_run=dry_run)
		put_order = self.place_order(security_id=put_row['pe_security_id'], symbol=f"{underlying} {int(put_strike)} PE", exchange_segment='NSE_FNO', transaction_type=transaction_type, quantity=lot_size, order_type=order_type, product_type=product_type, price=float(put_row['pe_ltp']), lot_size=lot_size, instrument_name='OPTIDX', dry_run=dry_run)
		return {'strategy': 'STRANGLE', 'spot': spot, 'expiry': expiry, 'call_strike': call_strike, 'put_strike': put_strike, 'call_order': call_order, 'put_order': put_order}

	def correct_step_df_creation(self):
		# pdb.set_trace()
		self.correct_list = {} 
		names_list = instrument_df['SEM_CUSTOM_SYMBOL'].str.split(' ').str[0].unique().tolist()
		names_list = [name for name in names_list if isinstance(name, str) and '-' not in name and '%' not in name]

		pdb.set_trace()
		for name in names_list:
			if '-' in name or '%' in name:
				continue
			try:
				# Filter rows matching the specific symbol and criteria
				filtered_df = self.instrument_df[
					(self.instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(name, na=False)) &
					(self.instrument_df['SEM_EXM_EXCH_ID'] == 'NSE') &
					(self.instrument_df['SEM_EXCH_INSTRUMENT_TYPE'] == 'OP')
				]
				if filtered_df.empty:
					continue
				# Find the unique expiry date
				expiry_dates = filtered_df['SEM_EXPIRY_DATE'].unique()
				if len(expiry_dates) == 0:
					raise ValueError(f"No expiry date found for {name}")
				
				expiry = expiry_dates[0]  # Assuming the first expiry is the desired one

				# Filter for CE option type and calculate step values
				ce_condition = (
					(filtered_df['SEM_TRADING_SYMBOL'].str.startswith(name + '-')) &
					(filtered_df['SEM_CUSTOM_SYMBOL'].str.contains(name)) &
					(filtered_df['SEM_EXPIRY_DATE'] == expiry) &
					(filtered_df['SEM_OPTION_TYPE'] == 'CE')
				)
				
				new_df = filtered_df.loc[ce_condition].copy()
				new_df['SEM_STRIKE_PRICE'] = new_df['SEM_STRIKE_PRICE'].astype(int)

				sorted_strikes = sorted(new_df['SEM_STRIKE_PRICE'].to_list())
				differences = [sorted_strikes[i + 1] - sorted_strikes[i] for i in range(len(sorted_strikes) - 1)]
				
				difference_counts = Counter(differences)
				step_value, max_frequency = difference_counts.most_common(1)[0]

				# Update the step value for the symbol
				self.stock_step_df[name] = step_value
				self.correct_list[name] = step_value
				print(f"Correct list for {name} is {self.correct_list}")

			except Exception as e:
				self.logger.exception(f"Error processing {name}: {e}")
				# print(f"Error processing {name}: {e}")		

		
	def order_placement(self,tradingsymbol:str, exchange:str,quantity:int, price:int, trigger_price:int, order_type:str, transaction_type:str, trade_type:str,disclosed_quantity=0,after_market_order=False,validity ='DAY', amo_time='OPEN',bo_profit_value=None, bo_stop_loss_Value=None)->str:
		try:
			tradingsymbol = tradingsymbol.upper()
			exchange = exchange.upper()
			# script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.NSE_FNO, "BFO":self.Dhan.BSE_FNO, "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			self.order_Type = {'LIMIT': self.Dhan.LIMIT, 'MARKET': self.Dhan.MARKET,'STOPLIMIT': self.Dhan.SL, 'STOPMARKET': self.Dhan.SLM}
			product = {'MIS':self.Dhan.INTRA, 'MARGIN':self.Dhan.MARGIN, 'MTF':self.Dhan.MTF, 'CO':self.Dhan.CO,'BO':self.Dhan.BO, 'CNC': self.Dhan.CNC}
			Validity = {'DAY': "DAY", 'IOC': 'IOC'}
			transactiontype = {'BUY': self.Dhan.BUY, 'SELL': self.Dhan.SELL}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			amo_time_check = ['PRE_OPEN', 'OPEN', 'OPEN_30', 'OPEN_60']

			if after_market_order:
				if amo_time.upper() in ['PRE_OPEN', 'OPEN', 'OPEN_30', 'OPEN_60']:
					amo_time = amo_time.upper()
				else:
					raise Exception("amo_time value must be ['PRE_OPEN','OPEN','OPEN_30','OPEN_60']")			

			exchangeSegment = script_exchange[exchange]
			product_Type = product[trade_type.upper()]
			order_type = self.order_Type[order_type.upper()]
			order_side = transactiontype[transaction_type.upper()]
			time_in_force = Validity[validity.upper()]
			security_check = self.instrument_df[((self.instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(self.instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(self.instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
			if security_check.empty:
				raise Exception("Check the Tradingsymbol")
			security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']

			order = self.Dhan.place_order(security_id=str(security_id), exchange_segment=exchangeSegment,
											   transaction_type=order_side, quantity=int(quantity),
											   order_type=order_type, product_type=product_Type, price=float(price),
											   trigger_price=float(trigger_price),disclosed_quantity=int(disclosed_quantity),
					after_market_order=after_market_order, validity=time_in_force, amo_time=amo_time,
					bo_profit_value=bo_profit_value, bo_stop_loss_Value=bo_stop_loss_Value)
			
			if order['status']=='failure':
				raise Exception(order)

			orderid = order["data"]["orderId"]
			return str(orderid)
		except Exception as e:
			print(f"'Got exception in place_order as {e}")
			return None
	
	
	def modify_order(self, order_id, order_type, quantity, price=0, trigger_price=0, disclosed_quantity=0, validity='DAY',leg_name = None):
		try:
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			self.order_Type = {'LIMIT': self.Dhan.LIMIT, 'MARKET': self.Dhan.MARKET,'STOPLIMIT': self.Dhan.SL, 'STOPMARKET': self.Dhan.SLM}
			product = {'MIS':self.Dhan.INTRA, 'MARGIN':self.Dhan.MARGIN, 'MTF':self.Dhan.MTF, 'CO':self.Dhan.CO,'BO':self.Dhan.BO, 'CNC': self.Dhan.CNC}
			Validity = {'DAY': "DAY", 'IOC': 'IOC'}
			transactiontype = {'BUY': self.Dhan.BUY, 'SELL': self.Dhan.SELL}
			order_type = self.order_Type[order_type.upper()]
			time_in_force = Validity[validity.upper()]
			leg_name_check = ['ENTRY_LEG','TARGET_LEG','STOP_LOSS_LEG']
			if leg_name is not None:
				if leg_name.upper() in leg_name_check:
					leg_name = leg_name.upper()
				else:
					raise Exception(f'Leg Name value must be "["ENTRY_LEG","TARGET_LEG","STOP_LOSS_LEG"]"')
				
			response = self.Dhan.modify_order(order_id =order_id, order_type=order_type, leg_name=leg_name, quantity=int(quantity), price=float(price), trigger_price=float(trigger_price), disclosed_quantity=int(disclosed_quantity), validity=time_in_force)
			if response['status']=='failure':
				raise Exception(response)
			else:
				orderid = response["data"]["orderId"]
				return str(orderid)
		except Exception as e:
			print(f'Got exception in modify_order as {e}')
			

	def cancel_order(self,OrderID:str)->None:
		try:
			response = self.Dhan.cancel_order(order_id=OrderID)
			if response['status']=='failure':
				raise Exception(response)
			else:
				return response['data']['orderStatus']			
		except Exception as e:
			print(f'Got exception in cancel_order as {e}')
		
	
	def place_slice_order(self, tradingsymbol, exchange, transaction_type, quantity,
                           order_type, trade_type, price, trigger_price=0, disclosed_quantity=0,
                           after_market_order=False, validity='DAY', amo_time='OPEN',
                           bo_profit_value=None, bo_stop_loss_Value=None):
		try:
			tradingsymbol = tradingsymbol.upper()
			exchange = exchange.upper()
			# script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.NSE_FNO, "BFO":self.Dhan.BSE_FNO, "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			self.order_Type = {'LIMIT': self.Dhan.LIMIT, 'MARKET': self.Dhan.MARKET,'STOPLIMIT': self.Dhan.SL, 'STOPMARKET': self.Dhan.SLM}
			product = {'MIS':self.Dhan.INTRA, 'MARGIN':self.Dhan.MARGIN, 'MTF':self.Dhan.MTF, 'CO':self.Dhan.CO,'BO':self.Dhan.BO, 'CNC': self.Dhan.CNC}
			Validity = {'DAY': "DAY", 'IOC': 'IOC'}
			transactiontype = {'BUY': self.Dhan.BUY, 'SELL': self.Dhan.SELL}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			amo_time_check = ['PRE_OPEN', 'OPEN', 'OPEN_30', 'OPEN_60']

			if after_market_order:
				if amo_time.upper() in ['PRE_OPEN', 'OPEN', 'OPEN_30', 'OPEN_60']:
					amo_time = amo_time.upper()
				else:
					raise Exception("amo_time value must be ['PRE_OPEN','OPEN','OPEN_30','OPEN_60']")			

			exchangeSegment = script_exchange[exchange]
			product_Type = product[trade_type.upper()]
			order_type = self.order_Type[order_type.upper()]
			order_side = transactiontype[transaction_type.upper()]
			time_in_force = Validity[validity.upper()]
			security_check = self.instrument_df[((self.instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(self.instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(self.instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
			if security_check.empty:
				raise Exception("Check the Tradingsymbol")
			security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
			order = self.Dhan.place_slice_order(security_id=str(security_id), exchange_segment=exchangeSegment,
											   transaction_type=order_side, quantity=quantity,
											   order_type=order_type, product_type=product_Type, price=price,
											   trigger_price=trigger_price,disclosed_quantity=disclosed_quantity,
					after_market_order=after_market_order, validity=time_in_force, amo_time=amo_time,
					bo_profit_value=bo_profit_value, bo_stop_loss_Value=bo_stop_loss_Value)

			if order['status']=='failure':
				raise Exception(order)
			
			if type(order["data"])!=list:
				orderid = order["data"]["orderId"]
				orderid = str(orderid)
			if type(order["data"])==list:
				id_list = order["data"]
				orderid = [str(data['orderId']) for data in id_list]
			return orderid
		except Exception as e:
			print(f"'Got exception in place_order as {e}")
			return None	

	def kill_switch(self,action):
		try:
			active = {'ON':'ACTIVATE','OFF':'DEACTIVATE'}
			current_action = active[action.upper()]

			killswitch_response = self.Dhan.kill_switch(current_action)	
			if 'killSwitchStatus' in killswitch_response['data'].keys():
				return killswitch_response['data']['killSwitchStatus']
			else:
				return killswitch_response
		except Exception as e:
			self.logger.exception(f"Error at Kill switch as {e}")



	def get_live_pnl(self):
		"""
			use to get live pnl
			pnl()
		"""
		try:
			pos_book = self.Dhan.get_positions()
			if pos_book['status'] == 'failure':
				raise Exception(pos_book)
			live_pnl = 0.0
			for pos_ in pos_book.get('data', []) or []:
				realized = float(pos_.get('realizedProfit', 0) or 0)
				unrealized = float(pos_.get('unrealizedProfit', 0) or 0)
				live_pnl += realized + unrealized
			return live_pnl
		except Exception as e:
			print(f"got exception in pnl as {e}")
			self.logger.exception(f'got exception in pnl as {e} ')
			return 0

	def normalize_option_chain(self, response: dict):
		data = self.unwrap_sdk_data(response)
		spot = float(data['last_price'])
		option_chain = data.get('oc', {}) or {}
		rows = []
		for strike_key, strike_payload in sorted(option_chain.items(), key=lambda item: float(item[0])):
			row = {'strike': float(strike_key)}
			for side in ('ce', 'pe'):
				leg = strike_payload.get(side) or {}
				greeks = leg.get('greeks') or {}
				row[f'{side}_security_id'] = str(leg['security_id']) if leg.get('security_id') is not None else None
				row[f'{side}_ltp'] = leg.get('last_price')
				row[f'{side}_avg_price'] = leg.get('average_price')
				row[f'{side}_oi'] = leg.get('oi')
				row[f'{side}_oi_change'] = leg.get('oi_change')
				row[f'{side}_volume'] = leg.get('volume')
				row[f'{side}_iv'] = leg.get('implied_volatility')
				row[f'{side}_bid_price'] = leg.get('top_bid_price')
				row[f'{side}_bid_qty'] = leg.get('top_bid_quantity')
				row[f'{side}_ask_price'] = leg.get('top_ask_price')
				row[f'{side}_ask_qty'] = leg.get('top_ask_quantity')
				row[f'{side}_delta'] = greeks.get('delta')
				row[f'{side}_gamma'] = greeks.get('gamma')
				row[f'{side}_theta'] = greeks.get('theta')
				row[f'{side}_vega'] = greeks.get('vega')
			rows.append(row)
		return spot, rows

	def fetch_option_chain_df(self, under_security_id: int, expiry: str, under_exchange_segment: str = 'IDX_I'):
		response = self.Dhan.option_chain(under_security_id=under_security_id, under_exchange_segment=under_exchange_segment, expiry=expiry)
		spot, rows = self.normalize_option_chain(response)
		return pd.DataFrame(rows), spot

	def find_atm_row(self, chain_df: pd.DataFrame, spot: float):
		return chain_df.iloc[(chain_df['strike'] - spot).abs().argsort().iloc[0]]

	def check_margin_requirement(self, security_id: str, exchange_segment: str, transaction_type: str, quantity: int, product_type: str, price: float, trigger_price: float = 0):
		margin_response = self.Dhan.margin_calculator(security_id=security_id, exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, product_type=product_type, price=price, trigger_price=trigger_price)
		funds_response = self.Dhan.get_fund_limits()
		margin = self.unwrap_sdk_data(margin_response)
		funds = self.unwrap_sdk_data(funds_response)
		total_margin = margin.get('totalMargin', 0.0)
		available_balance = funds.get('availabelBalance', 0.0)
		return {'total_margin': total_margin, 'available_balance': available_balance, 'brokerage': margin.get('brokerage', 0.0), 'leverage': margin.get('leverage'), 'sufficient': available_balance >= total_margin, 'shortfall': max(0.0, total_margin - available_balance)}

	def get_balance(self):
		try:
			response = self.Dhan.get_fund_limits()
			if response['status']!='failure':
				balance = float(response['data']['availabelBalance'])
				return balance
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Error at Gettting balance as {e}")
			self.logger.exception(f"Error at Gettting balance as {e}")
			return 0
	

	def convert_to_date_time(self,time):
		return self.Dhan.convert_to_date_time(time)
	

	def get_start_date(self):
		try:
			instrument_df = self.instrument_df.copy()
			from_date= datetime.datetime.now()-datetime.timedelta(days=100)
			start_date = (datetime.datetime.now()-datetime.timedelta(days=5)).strftime('%Y-%m-%d')
			from_date = from_date.strftime('%Y-%m-%d')
			to_date = datetime.datetime.now().strftime('%Y-%m-%d')
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			tradingsymbol = "NIFTY"
			exchange = "NSE"
			exchange_segment = self.Dhan.INDEX
			security_id 	= instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_SMST_SECURITY_ID']
			instrument_type = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_INSTRUMENT_NAME']
			expiry_code 	= instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_EXPIRY_CODE']
			time.sleep(0.5)
			ohlc = self.Dhan.historical_daily_data(int(security_id),exchange_segment,instrument_type,from_date,to_date,int(expiry_code))
			if ohlc['status']!='failure':
				df = pd.DataFrame(ohlc['data'])
				if not df.empty:
					df['timestamp'] = df['timestamp'].apply(lambda x: self.convert_to_date_time(x))
					start_date = df.iloc[-2]['timestamp']
					start_date = start_date.strftime('%Y-%m-%d')
					return start_date, to_date
				else:
					return start_date, to_date
			else:
				return start_date, to_date			
		except Exception as e:
			self.logger.exception(f"Error at getting start date as {e}")
			return start_date, to_date

	def get_historical_data(self,tradingsymbol,exchange,timeframe, debug="NO"):			
		try:
			tradingsymbol = tradingsymbol.upper()
			exchange = exchange.upper()
			instrument_df = self.instrument_df.copy()
			from_date= datetime.datetime.now()-datetime.timedelta(days=365)
			from_date = from_date.strftime('%Y-%m-%d')
			to_date = datetime.datetime.now().strftime('%Y-%m-%d') 
			# script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.NSE_FNO, "BFO":self.Dhan.BSE_FNO, "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			exchange_segment = script_exchange[exchange]
			index_exchange = {"NIFTY":'NSE',"BANKNIFTY":"NSE","FINNIFTY":"NSE","MIDCPNIFTY":"NSE","BANKEX":"BSE","SENSEX":"BSE"}
			if tradingsymbol in index_exchange:
				exchange =index_exchange[tradingsymbol]

			if tradingsymbol in self.commodity_step_dict.keys():
				security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==tradingsymbol.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
				if security_check.empty:
					raise Exception("Check the Tradingsymbol or Exchange")
				security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
				tradingsymbol = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_CUSTOM_SYMBOL']
			else:						
				security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
				if security_check.empty:
					raise Exception("Check the Tradingsymbol or Exchange")
				security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']						

			Symbol 			= instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_TRADING_SYMBOL']
			instrument_type = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_INSTRUMENT_NAME']
			if 'FUT' in instrument_type and timeframe.upper()=="DAY":
				raise Exception('For Future or Commodity, DAY - Timeframe not supported by API, SO choose another timeframe')			
			expiry_code 	= instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_EXPIRY_CODE']
			if timeframe in ['1', '5', '15', '25', '60']:
				interval = int(timeframe)
			elif timeframe.upper()=="DAY":
				pass
			else:
				raise Exception("interval value must be ['1','5','15','25','60','DAY']")
			if timeframe.upper() == "DAY":
				time.sleep(2)			
				ohlc = self.Dhan.historical_daily_data(int(security_id),exchange_segment,instrument_type,from_date,to_date,int(expiry_code))
			else:
				time.sleep(2)
				ohlc = self.Dhan.intraday_minute_data(str(security_id),exchange_segment,instrument_type,self.start_date,self.end_date,int(interval))
			
			if debug.upper()=="YES":
				print(ohlc)
			
			if ohlc['status']!='failure':
				df = pd.DataFrame(ohlc['data'])
				if not df.empty:
					df['timestamp'] = df['timestamp'].apply(lambda x: self.convert_to_date_time(x))
					return df
				else:
					return df
			else:
				raise Exception(ohlc) 
		except Exception as e:
			print(f"Exception in Getting OHLC data as {e}")
			self.logger.exception(f"Exception in Getting OHLC data as {e}")
			# traceback.print_exc()

	def get_intraday_data(self,tradingsymbol,exchange,timeframe, debug="NO"):			
		try:
			tradingsymbol = tradingsymbol.upper()
			exchange = exchange.upper()
			instrument_df = self.instrument_df.copy()
			available_frames = {
				2: '2min',    # 2 minutes
				3: '3min',    # 3 minutes
				5: '5min',    # 5 minutes
				10: '10min',   # 10 minutes
				15: '15min',   # 15 minutes
				30: '30min',   # 30 minutes
				60: '60min'    # 60 minutes
			}

			start_date =datetime.datetime.now().strftime('%Y-%m-%d')
			end_date = datetime.datetime.now().strftime('%Y-%m-%d')

			# script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.NSE_FNO, "BFO":self.Dhan.BSE_FNO, "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX}
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			exchange_segment = script_exchange[exchange]
			index_exchange = {"NIFTY":'NSE',"BANKNIFTY":"NSE","FINNIFTY":"NSE","MIDCPNIFTY":"NSE","BANKEX":"BSE","SENSEX":"BSE"}
			if tradingsymbol in index_exchange:
				exchange =index_exchange[tradingsymbol]
			if tradingsymbol in self.commodity_step_dict.keys():
				security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==tradingsymbol.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
				if security_check.empty:
					raise Exception("Check the Tradingsymbol or Exchange")
				security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
				tradingsymbol = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_CUSTOM_SYMBOL']
			else:						
				security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
				if security_check.empty:
					raise Exception("Check the Tradingsymbol or Exchange")
				security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']	

			instrument_type = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])].iloc[-1]['SEM_INSTRUMENT_NAME']
			time.sleep(2)
			ohlc = self.Dhan.intraday_minute_data(str(security_id),exchange_segment,instrument_type,start_date,end_date,int(1))
			
			if debug.upper()=="YES":
				print(ohlc)

			if ohlc['status']!='failure':
				df = pd.DataFrame(ohlc['data'])
				if not df.empty:
					df['timestamp'] = df['timestamp'].apply(lambda x: self.convert_to_date_time(x))
					if timeframe==1:
						return df
					df = self.resample_timeframe(df,available_frames[timeframe])
					return df
				else:
					return df
			else:
				raise Exception(ohlc) 
		except Exception as e:
			print(e)
			self.logger.exception(f"Exception in Getting OHLC data as {e}")
			traceback.print_exc()

	def resample_timeframe(self, df, timeframe='5min'):
		try:
			df['timestamp'] = pd.to_datetime(df['timestamp'])
			df.set_index('timestamp', inplace=True)
			
			market_start = pd.to_datetime("09:15:00").time()
			market_end = pd.to_datetime("15:30:00").time()

			timezone = pytz.timezone('Asia/Kolkata')
						
			resampled_data = []
			for date, group in df.groupby(df.index.date):
				origin_time = timezone.localize(pd.Timestamp(f"{date} 09:15:00"))
				daily_data = group.between_time(market_start, market_end)
				if not daily_data.empty:
					resampled = daily_data.resample(timeframe, origin=origin_time).agg({
						'open': 'first',
						'high': 'max',
						'low': 'min',
						'close': 'last',
						'volume': 'sum'
					}).dropna(how='all')  # Drop intervals with no data
					resampled_data.append(resampled)

			if resampled_data:
				resampled_df = pd.concat(resampled_data)
			else:
				resampled_df = pd.DataFrame(columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])

			resampled_df.reset_index(inplace=True)
			return resampled_df

		except Exception as e:
			self.logger.exception(f"Error in resampling timeframe: {e}")
			return pd.DataFrame()

	
	def get_lot_size(self,tradingsymbol: str):
		instrument_df = self.instrument_df.copy()
		data = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))]
		if len(data) == 0:
			self.logger.exception("Enter valid Script Name")
			print("Enter valid Script Name")
			return 0
		else:
			return int(data.iloc[0]['SEM_LOT_UNITS'])
		

	def get_ltp_data(self,names, debug="NO"):
		try:
			instrument_df = self.instrument_df.copy()
			instruments = {'NSE_EQ':[],'IDX_I':[],'NSE_FNO':[],'NSE_CURRENCY':[],'BSE_EQ':[],'BSE_FNO':[],'BSE_CURRENCY':[],'MCX_COMM':[]}
			instrument_names = {}
			NFO = ["BANKNIFTY","NIFTY","MIDCPNIFTY","FINNIFTY"]
			BFO = ['SENSEX','BANKEX']
			equity = ['CALL','PUT','FUT']			
			exchange_index = {"BANKNIFTY": "NSE_IDX","NIFTY":"NSE_IDX","MIDCPNIFTY":"NSE_IDX", "FINNIFTY":"NSE_IDX","SENSEX":"BSE_IDX","BANKEX":"BSE_IDX"}
			if not isinstance(names, list):
				names = [names]
			for name in names:
				try:
					name = name.upper()
					if name in exchange_index.keys():
						security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))]
						if security_check.empty:
							raise Exception("Check the Tradingsymbol")
						security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
						instruments['IDX_I'].append(int(security_id))
						instrument_names[str(security_id)]=name
					elif name in self.commodity_step_dict.keys():
						security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==name.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
						if security_check.empty:
							raise Exception("Check the Tradingsymbol")
						security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
						instruments['MCX_COMM'].append(int(security_id))
						instrument_names[str(security_id)]=name
					else:
						security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))]
						if security_check.empty:
							raise Exception("Check the Tradingsymbol")						
						security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
						nfo_check = ['NSE_FNO' for nfo in NFO if nfo in name]
						bfo_check = ['BSE_FNO' for bfo in BFO if bfo in name]
						exchange_nfo ='NSE_FNO' if len(nfo_check)!=0 else False
						exchange_bfo = 'BSE_FNO' if len(bfo_check)!=0 else False
						if not exchange_nfo and not exchange_bfo:
							eq_check =['NSE_FNO' for nfo in equity if nfo in name]
							exchange_eq ='NSE_FNO' if len(eq_check)!=0 else "NSE_EQ"
						else:
							exchange_eq="NSE_EQ"
						exchange ='NSE_FNO' if exchange_nfo else ('BSE_FNO' if exchange_bfo else exchange_eq)
						trail_exchange = exchange
						mcx_check = ['MCX_COMM' for mcx in self.commodity_step_dict.keys() if mcx in name]
						exchange = "MCX_COMM" if len(mcx_check)!=0 else exchange
						if exchange == "MCX_COMM": 
							if instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))&(instrument_df['SEM_EXM_EXCH_ID']=='MCX')].empty:
								exchange = trail_exchange
						if exchange == "MCX_COMM":
							security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))&(instrument_df['SEM_EXM_EXCH_ID']=='MCX')]
							if security_check.empty:
								raise Exception("Check the Tradingsymbol")	
							security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
						instruments[exchange].append(int(security_id))
						instrument_names[str(security_id)]=name
				except Exception as e:
					print(f"Exception for instrument name {name} as {e}")
			time.sleep(2)
			# pdb.set_trace(header = f"security_id {security_id}")
			# print(instruments)
			data = self.Dhan.ticker_data(instruments)
			ltp_data=dict()
			
			if debug.upper()=="YES":
				print(data)			

			if data['status']!='failure':
				all_values = data['data']['data']
				for exchange in data['data']['data']:
					for key, values in all_values[exchange].items():
						symbol = instrument_names[key]
						ltp_data[symbol] = values['last_price']
			else:
				raise Exception(data)
			
			return ltp_data
		except Exception as e:
			print(f"Exception at calling ltp as {e}")
			self.logger.exception(f"Exception at calling ltp as {e}")
			return dict()


	def ltp_call(self,instruments):
		try:
			url = "https://api.dhan.co/v2/marketfeed/ltp"
			headers = {
				'Accept': 'application/json',
				'Content-Type': 'application/json',
				'access-token': self.token_id,
				'client-id': self.ClientCode
			}
			
			data = dict()
			for key, value in instruments.items():
				if len(value)!=0:
					data[key]=value
					data[key] = [int(val) if isinstance(val, np.integer) else float(val) if isinstance(val, np.floating) else val for val in value]

			response = requests.post(url, headers=headers, json=data)
			if response.status_code == 200:
				return response.json()
			else:
				raise Exception(f"Failed to retrieve LTP. Status Code: {response.status_code}, Response: {response.text}")		
		except Exception as e:
			self.logger.exception(f"Exception at getting ltp from api as {e}")



	def ATM_Strike_Selection(self, Underlying, Expiry):
		try:
			Underlying = Underlying.upper()
			strike = 0
			exchange_index = {"BANKNIFTY": "NSE","NIFTY":"NSE","MIDCPNIFTY":"NSE", "FINNIFTY":"NSE","SENSEX":"BSE","BANKEX":"BSE"}
			instrument_df = self.instrument_df.copy()

			instrument_df['SEM_EXPIRY_DATE'] = pd.to_datetime(instrument_df['SEM_EXPIRY_DATE'], errors='coerce')
			instrument_df['ContractExpiration'] = instrument_df['SEM_EXPIRY_DATE'].dt.date
			instrument_df['ContractExpiration'] = instrument_df['ContractExpiration'].astype(str)

			if Underlying in exchange_index:
				exchange = exchange_index[Underlying]
				expiry_exchange = 'INDEX'
			elif Underlying in self.commodity_step_dict.keys():
				exchange = "MCX"
				expiry_exchange = exchange
			else:
				# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
				exchange = "NSE"
				expiry_exchange = exchange

			expiry_list = self.get_expiry_list(Underlying=Underlying, exchange = expiry_exchange)

			if len(expiry_list)==0:
				print(f"Unable to find the correct Expiry for {Underlying}")
				return None
			if len(expiry_list)<Expiry:
				Expiry_date = expiry_list[-1]
			else:
				Expiry_date = expiry_list[Expiry]

			ltp_data = self.get_ltp_data(Underlying)
			ltp = ltp_data[Underlying]
			if Underlying in self.index_step_dict:
				step = self.index_step_dict[Underlying]
			elif Underlying in self.stock_step_df:
				step = self.stock_step_df[Underlying]
			elif Underlying in self.commodity_step_dict:
				step = self.commodity_step_dict[Underlying]
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)
			strike = round(ltp/step) * step
			
			if Underlying in self.index_step_dict:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')
			elif exchange =="MCX": 		
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') & (instrument_df['SM_SYMBOL_NAME']==Underlying) 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')	& (instrument_df['SM_SYMBOL_NAME']==Underlying)
			elif Underlying in self.stock_step_df:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE')
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)

			ce_df = instrument_df[ce_condition].copy()
			pe_df = instrument_df[pe_condition].copy()

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the ATM strike for the {Underlying}")

			ce_df['SEM_STRIKE_PRICE'] = ce_df['SEM_STRIKE_PRICE'].astype("int")
			pe_df['SEM_STRIKE_PRICE'] = pe_df['SEM_STRIKE_PRICE'].astype("int")

			ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==strike]
			pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==strike]

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the ATM strike for the {Underlying}")			

			if ce_df.empty or len(ce_df)==0:
				ce_df['diff'] = abs(ce_df['SEM_STRIKE_PRICE'] - strike)
				closest_index = ce_df['diff'].idxmin()
				strike = ce_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==strike]
			
			ce_df = ce_df.iloc[-1]	

			if pe_df.empty or len(pe_df)==0:
				pe_df['diff'] = abs(pe_df['SEM_STRIKE_PRICE'] - strike)
				closest_index = pe_df['diff'].idxmin()
				strike = pe_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==strike]
			
			pe_df = pe_df.iloc[-1]			

			ce_strike = ce_df['SEM_CUSTOM_SYMBOL']
			pe_strike = pe_df['SEM_CUSTOM_SYMBOL']

			if ce_strike== None:
				self.logger.info("No Scripts to Select from ce_spot_difference for ")
				print("No Scripts to Select from ce_spot_difference for ")
				return
			if pe_strike == None:
				self.logger.info("No Scripts to Select from pe_spot_difference for ")
				print("No Scripts to Select from pe_spot_difference for ")
				return
			
			return ce_strike, pe_strike, strike
		except Exception as e:
			print('exception got in ce_pe_option_df',e)
			return None, None, strike

	def OTM_Strike_Selection(self, Underlying, Expiry,OTM_count=1):
		try:
			Underlying = Underlying.upper()
			# Expiry = pd.to_datetime(Expiry, format='%d-%m-%Y').strftime('%Y-%m-%d')
			exchange_index = {"BANKNIFTY": "NSE","NIFTY":"NSE","MIDCPNIFTY":"NSE", "FINNIFTY":"NSE","SENSEX":"BSE","BANKEX":"BSE"}
			instrument_df = self.instrument_df.copy()

			instrument_df['SEM_EXPIRY_DATE'] = pd.to_datetime(instrument_df['SEM_EXPIRY_DATE'], errors='coerce')
			instrument_df['ContractExpiration'] = instrument_df['SEM_EXPIRY_DATE'].dt.date
			instrument_df['ContractExpiration'] = instrument_df['ContractExpiration'].astype(str)

			if Underlying in exchange_index:
				exchange = exchange_index[Underlying]
				expiry_exchange = 'INDEX'
			elif Underlying in self.commodity_step_dict.keys():
				exchange = "MCX"
				expiry_exchange = exchange
			else:
				# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
				exchange = "NSE"
				expiry_exchange = exchange

			expiry_list = self.get_expiry_list(Underlying=Underlying, exchange = expiry_exchange)

			if len(expiry_list)==0:
				print(f"Unable to find the correct Expiry for {Underlying}")
				return None
			if len(expiry_list)<Expiry:
				Expiry_date = expiry_list[-1]
			else:
				Expiry_date = expiry_list[Expiry]			
	
			ltp_data = self.get_ltp_data(Underlying)
			ltp = ltp_data[Underlying]
			if Underlying in self.index_step_dict:
				step = self.index_step_dict[Underlying]
			elif Underlying in self.stock_step_df:
				step = self.stock_step_df[Underlying]
			elif Underlying in self.commodity_step_dict:
				step = self.commodity_step_dict[Underlying]
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)
			strike = round(ltp/step) * step
			

			if OTM_count<1:
				return "INVALID OTM DISTANCE"

			step = int(OTM_count*step)

			ce_OTM_price = strike+step
			pe_OTM_price = strike-step

			if Underlying in self.index_step_dict:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')
			elif exchange =="MCX": 		
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') & (instrument_df['SM_SYMBOL_NAME']==Underlying) 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')	& (instrument_df['SM_SYMBOL_NAME']==Underlying)
			elif Underlying in self.stock_step_df:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE')
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')	
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)				 			
			
			ce_df = instrument_df[ce_condition].copy()
			pe_df = instrument_df[pe_condition].copy()

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the OTM strike for the {Underlying}")			

			ce_df['SEM_STRIKE_PRICE'] = ce_df['SEM_STRIKE_PRICE'].astype("int")
			pe_df['SEM_STRIKE_PRICE'] = pe_df['SEM_STRIKE_PRICE'].astype("int")

			ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==ce_OTM_price]
			pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==pe_OTM_price]

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the ITM strike for the {Underlying}")			

			if ce_df.empty or len(ce_df)==0:
				ce_df['diff'] = abs(ce_df['SEM_STRIKE_PRICE'] - ce_OTM_price)
				closest_index = ce_df['diff'].idxmin()
				ce_OTM_price = ce_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==ce_OTM_price]
			
			ce_df = ce_df.iloc[-1]	

			if pe_df.empty or len(pe_df)==0:
				pe_df['diff'] = abs(pe_df['SEM_STRIKE_PRICE'] - pe_OTM_price)
				closest_index = pe_df['diff'].idxmin()
				pe_OTM_price = pe_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==pe_OTM_price]
			
			pe_df = pe_df.iloc[-1]			

			ce_strike = ce_df['SEM_CUSTOM_SYMBOL']
			pe_strike = pe_df['SEM_CUSTOM_SYMBOL']

			if ce_strike== None:
				self.logger.info("No Scripts to Select from ce_spot_difference for ")
				print("No Scripts to Select from ce_spot_difference for ")
				return
			if pe_strike == None:
				self.logger.info("No Scripts to Select from pe_spot_difference for ")
				print("No Scripts to Select from pe_spot_difference for ")
				return
			
			return ce_strike, pe_strike, ce_OTM_price, pe_OTM_price
		except Exception as e:
			print(f"Getting Error at OTM strike Selection as {e}")
			return None,None,0,0


	def ITM_Strike_Selection(self, Underlying, Expiry, ITM_count=1):
		try:
			Underlying = Underlying.upper()
			# Expiry = pd.to_datetime(Expiry, format='%d-%m-%Y').strftime('%Y-%m-%d')
			exchange_index = {"BANKNIFTY": "NSE","NIFTY":"NSE","MIDCPNIFTY":"NSE", "FINNIFTY":"NSE","SENSEX":"BSE","BANKEX":"BSE"}
			instrument_df = self.instrument_df.copy()

			instrument_df['SEM_EXPIRY_DATE'] = pd.to_datetime(instrument_df['SEM_EXPIRY_DATE'], errors='coerce')
			instrument_df['ContractExpiration'] = instrument_df['SEM_EXPIRY_DATE'].dt.date
			instrument_df['ContractExpiration'] = instrument_df['ContractExpiration'].astype(str)

			if Underlying in exchange_index:
				exchange = exchange_index[Underlying]
				expiry_exchange = 'INDEX'
			elif Underlying in self.commodity_step_dict.keys():
				exchange = "MCX"
				expiry_exchange = exchange
			else:
				# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
				exchange = "NSE"
				expiry_exchange = exchange

			expiry_list = self.get_expiry_list(Underlying=Underlying, exchange = expiry_exchange)

			if len(expiry_list)==0:
				print(f"Unable to find the correct Expiry for {Underlying}")
				return None
			if len(expiry_list)<Expiry:
				Expiry_date = expiry_list[-1]
			else:
				Expiry_date = expiry_list[Expiry]			
	
			ltp_data = self.get_ltp_data(Underlying)
			ltp = ltp_data[Underlying]
			if Underlying in self.index_step_dict:
				step = self.index_step_dict[Underlying]
			elif Underlying in self.stock_step_df:
				step = self.stock_step_df[Underlying]
			elif Underlying in self.commodity_step_dict:
				step = self.commodity_step_dict[Underlying]
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)
			strike = round(ltp/step) * step

			if ITM_count<1:
				return "INVALID ITM DISTANCE"
			
			step = int(ITM_count*step)
			ce_ITM_price = strike-step
			pe_ITM_price = strike+step

			if Underlying in self.index_step_dict:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')
			elif exchange =="MCX": 		
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE') & (instrument_df['SM_SYMBOL_NAME']==Underlying) 
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.contains(Underlying))|(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')	& (instrument_df['SM_SYMBOL_NAME']==Underlying)
			elif Underlying in self.stock_step_df:
				ce_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='CE')
				pe_condition = (instrument_df['SEM_EXM_EXCH_ID'] == exchange) & ((instrument_df['SEM_TRADING_SYMBOL'].str.startswith(Underlying + '-'))&(instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(Underlying))) & (instrument_df['ContractExpiration'] == Expiry_date) & (instrument_df['SEM_OPTION_TYPE']=='PE')
			else:
				data = f'{Underlying} Not in the step list'
				raise Exception(data)			
			 			
			ce_df = instrument_df[ce_condition].copy()
			pe_df = instrument_df[pe_condition].copy()

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the ITM strike for the {Underlying}")			

			ce_df['SEM_STRIKE_PRICE'] = ce_df['SEM_STRIKE_PRICE'].astype("int")
			pe_df['SEM_STRIKE_PRICE'] = pe_df['SEM_STRIKE_PRICE'].astype("int")

			ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==ce_ITM_price].copy()
			pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==pe_ITM_price]

			if ce_df.empty or pe_df.empty:
				raise Exception(f"Unable to find the ITM strike for the {Underlying}")

			if ce_df.empty or len(ce_df)==0:
				ce_df['diff'] = abs(ce_df['SEM_STRIKE_PRICE'] - ce_ITM_price)
				closest_index = ce_df['diff'].idxmin()
				ce_ITM_price = ce_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				ce_df =ce_df[ce_df['SEM_STRIKE_PRICE']==ce_ITM_price]
			
			ce_df = ce_df.iloc[-1]	

			if pe_df.empty or len(pe_df)==0:
				pe_df['diff'] = abs(pe_df['SEM_STRIKE_PRICE'] - pe_ITM_price)
				closest_index = pe_df['diff'].idxmin()
				pe_ITM_price = pe_df.loc[closest_index, 'SEM_STRIKE_PRICE']
				pe_df =pe_df[pe_df['SEM_STRIKE_PRICE']==pe_ITM_price]
			
			pe_df = pe_df.iloc[-1]			

			ce_strike = ce_df['SEM_CUSTOM_SYMBOL']
			pe_strike = pe_df['SEM_CUSTOM_SYMBOL']

			if ce_strike== None:
				self.logger.info("No Scripts to Select from ce_spot_difference for ")
				print("No Scripts to Select from ce_spot_difference for ")
				return
			if pe_strike == None:
				self.logger.info("No Scripts to Select from pe_spot_difference for ")
				print("No Scripts to Select from pe_spot_difference for ")
				return
			
			return ce_strike, pe_strike, ce_ITM_price, pe_ITM_price
		except Exception as e:
			print(f"Getting Error at OTM strike Selection as {e}")
			return None,None,0,0

	def cancel_all_orders(self) -> dict:
		try:
			order_details=dict()
			product_detail ={'MIS':self.Dhan.INTRA, 'MARGIN':self.Dhan.MARGIN, 'MTF':self.Dhan.MTF, 'CO':self.Dhan.CO,'BO':self.Dhan.BO, 'CNC': self.Dhan.CNC}
			product = product_detail['MIS']
			time.sleep(1)
			data = self.Dhan.get_order_list()["data"]
			if data is None or len(data)==0:
				return order_details
			orders = pd.DataFrame(data)
			if orders.empty:
				return order_details
			trigger_pending_orders = orders.loc[(orders['orderStatus'] == 'PENDING') & (orders['productType'] == product)]
			open_orders = orders.loc[(orders['orderStatus'] == 'TRANSIT') & (orders['productType'] == product)]
			for index, row in trigger_pending_orders.iterrows():
				response = self.Dhan.cancel_order(row['orderId'])

			for index, row in open_orders.iterrows():
				response = self.Dhan.cancel_order(row['orderId'])
			position_dict = self.Dhan.get_positions()["data"]
			positions_df = pd.DataFrame(position_dict)
			if positions_df.empty:
				return order_details
			positions_df['netQty']=positions_df['netQty'].astype(int)
			bought = positions_df.loc[(positions_df['netQty'] > 0) & (positions_df["productType"] == product)]
			sold = positions_df.loc[(positions_df['netQty'] < 0) & (positions_df['productType'] == product)]

			for index, row in bought.iterrows():
				qty = int(row["netQty"])
				order = self.Dhan.place_order(security_id=str(row["securityId"]), exchange_segment=row["exchangeSegment"],
												transaction_type=self.Dhan.SELL, quantity=qty,
												order_type=self.Dhan.MARKET, product_type=row["productType"], price=0,
												trigger_price=0)

				tradingsymbol = row['tradingSymbol']
				sell_order_id= order["data"]["orderId"]
				order_details[tradingsymbol]=dict({'orderid':sell_order_id,'price':0})
				time.sleep(0.5)

			for index, row in sold.iterrows():
				qty = int(row["netQty"]) * -1
				order = self.Dhan.place_order(security_id=str(row["securityId"]), exchange_segment=row["exchangeSegment"],
												transaction_type=self.Dhan.BUY, quantity=qty,
												order_type=self.Dhan.MARKET, product_type=row["productType"], price=0,
												trigger_price=0)
				tradingsymbol = row['tradingSymbol']
				buy_order_id=order["data"]["orderId"]
				order_details[tradingsymbol]=dict({'orderid':buy_order_id,'price':0})
				time.sleep(1)
			if len(order_details)!=0:
				_,order_price = self.order_report()
				for key,value in order_details.items():
					orderid = str(value['orderid'])
					if orderid in order_price:
						order_details[key]['price'] = order_price[orderid] 	
			return order_details
		except Exception as e:
			print(e)
			print("problem close all trades")
			self.logger.exception("problem close all trades")
			traceback.print_exc()

	def order_report(self) -> Tuple[Dict, Dict]:
		'''
		If watchlist has more than two stock, using order_report, get the order status and order execution price
		order_report()
		'''
		try:
			order_details= dict()
			order_exe_price= dict()
			time.sleep(1)
			status_df = self.Dhan.get_order_list()["data"]
			status_df = pd.DataFrame(status_df)
			if not status_df.empty:
				status_df.set_index('orderId',inplace=True)
				order_details = status_df['orderStatus'].to_dict()
				order_exe_price = status_df['averageTradedPrice'].to_dict()
			
			return order_details, order_exe_price
		except Exception as e:
			self.logger.exception(f"Exception in getting order report as {e}")
			return dict(), dict()

	def get_order_detail(self,orderid:str, debug= "NO")->dict:
		try:
			if orderid is None:
				raise Exception('Check the order id, Error as None')
			orderid = str(orderid)
			time.sleep(1)
			response = self.Dhan.get_order_by_id(orderid)
			if debug.upper()=="YES":
				print(response)
			if response['status']=='success':
				return response['data'][0]
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Error at getting order details as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}

	
	def get_order_status(self, orderid:str, debug= "NO")->str:
		try:
			if orderid is None:
				raise Exception('Check the order id, Error as None')			
			orderid = str(orderid)
			time.sleep(1)
			response = self.Dhan.get_order_by_id(orderid)
			if debug.upper()=="YES":
				print(response)			
			if response['status']=='success':
				return response['data'][0]['orderStatus']
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Error at getting order status as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}	


	def get_executed_price(self, orderid:str, debug= "NO")->int:
		try:
			if orderid is None:
				raise Exception('Check the order id, Error as None')			
			orderid = str(orderid)
			time.sleep(1)
			response = self.Dhan.get_order_by_id(orderid)
			if debug.upper()=="YES":
				print(response)				
			if response['status']=='success':
				return response['data'][0]['averageTradedPrice']
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Error at get_executed_price as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}

	def get_exchange_time(self,orderid:str, debug= "NO")->str:
		try:
			if orderid is None:
				raise Exception('Check the order id, Error as None')			
			orderid = str(orderid)
			time.sleep(1)
			response = self.Dhan.get_order_by_id(orderid)
			if debug.upper()=="YES":
				print(response)				
			if response['status']=='success':
				return response['data'][0]['exchangeTime']
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Error at get_exchange_time as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}			

	def get_holdings(self, debug= "NO"):
		try:
			time.sleep(1)
			response = self.Dhan.get_holdings()
			if debug.upper()=="YES":
				print(response)				
			if response['status']=='success':
				return pd.DataFrame(response['data'])
			else:
				raise Exception(response)		
		except Exception as e:
			print(f"Error at getting Holdings as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}

	def get_positions(self, debug= "NO"):
		try:
			time.sleep(1)
			response = self.Dhan.get_positions()
			if debug.upper()=="YES":
				print(response)				
			if response['status']=='success':
				return pd.DataFrame(response['data'])
			else:
				raise Exception(response)		
		except Exception as e:
			print(f"Error at getting Positions as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}			

	def get_orderbook(self, debug= "NO"):
		try:
			time.sleep(1)
			response = self.Dhan.get_order_list()
			if debug.upper()=="YES":
				print(response)				
			if response['status']=='success':
				return pd.DataFrame(response['data'])
			else:
				raise Exception(response)		
		except Exception as e:
			print(f"Error at get_orderbook as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}
	
	def get_trade_book(self, debug= "NO"):
		try:
			response = self.Dhan.get_order_list()
			if debug.upper()=="YES":
				print(response)			
			if response['status']=='success':
				return pd.DataFrame(response['data'])
			else:
				raise Exception(response)		
		except Exception as e:
			print(f"Error at get_trade_book as {e}")
			return {
				'status':'failure',
				'remarks':str(e),
				'data':response,
			}
		
		
	def get_option_greek(self, strike: int, expiry: int, asset: str, interest_rate: float, flag: str, scrip_type: str):
		try:
			asset = asset.upper()
			# expiry = pd.to_datetime(expiry_date, format='%d-%m-%Y').strftime('%Y-%m-%d')
			exchange_index = {"BANKNIFTY": "NSE", "NIFTY": "NSE", "MIDCPNIFTY": "NSE", "FINNIFTY": "NSE", "SENSEX": "BSE", "BANKEX": "BSE"}
			asset_dict = {'NIFTY BANK': "BANKNIFTY", "NIFTY 50": "NIFTY", 'NIFTY FIN SERVICE': 'FINNIFTY', 'NIFTY MID SELECT': 'MIDCPNIFTY', "SENSEX": "SENSEX", "BANKEX": "BANKEX"}

			if asset in asset_dict:
				inst_asset = asset_dict[asset]
			elif asset in asset_dict.values():
				inst_asset = asset
			else:
				inst_asset = asset

			if inst_asset in exchange_index:
				exchange = exchange_index[inst_asset]
				expiry_exchange = 'INDEX'
			elif inst_asset in self.commodity_step_dict.keys():
				exchange = "MCX"
				expiry_exchange = exchange
			else:
				# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
				exchange = "NSE"
				expiry_exchange = exchange

			expiry_list = self.get_expiry_list(Underlying=inst_asset, exchange = expiry_exchange)

			if len(expiry_list)==0:
				print(f"Unable to find the correct Expiry for {inst_asset}")
				return None
			if len(expiry_list)<expiry:
				expiry_date = expiry_list[-1]
			else:
				expiry_date = expiry_list[expiry]
				

			# exchange = exchange_index[inst_asset]

			instrument_df = self.instrument_df.copy()
			instrument_df['SEM_EXPIRY_DATE'] = pd.to_datetime(instrument_df['SEM_EXPIRY_DATE'], errors='coerce')
			instrument_df['ContractExpiration'] = instrument_df['SEM_EXPIRY_DATE'].dt.date.astype(str)

			# check_ecpiry = datetime.datetime.strptime(expiry_date, '%d-%m-%Y')


			data = instrument_df[
				# (instrument_df['SEM_EXM_EXCH_ID'] == exchange) &
				((instrument_df['SEM_TRADING_SYMBOL'].str.contains(inst_asset)) | 
				 (instrument_df['SEM_CUSTOM_SYMBOL'].str.contains(inst_asset))) &
				(instrument_df['ContractExpiration'] == expiry_date) &
				(instrument_df['SEM_STRIKE_PRICE'] == strike) &
				(instrument_df['SEM_OPTION_TYPE']==scrip_type)
			]

			if data.empty:
				self.logger.error('No data found for the specified parameters.')
				raise Exception('No data found for the specified parameters.')

			script_list = data['SEM_CUSTOM_SYMBOL'].tolist()
			script = script_list[0]

			days_to_expiry = (datetime.datetime.strptime(expiry_date, "%Y-%m-%d").date() - datetime.datetime.now().date()).days
			if days_to_expiry <= 0:
				days_to_expiry = 1

			ltp_data = self.get_ltp_data([asset,script])
			asset_price = ltp_data[asset]
			ltp = ltp_data[script]
			# asset_price = self.get_ltp(asset)
			# ltp = self.get_ltp(script)

			if scrip_type == 'CE':
				civ = mibian.BS([asset_price, strike, interest_rate, days_to_expiry], callPrice= ltp)
				cval = mibian.BS([asset_price, strike, interest_rate, days_to_expiry], volatility = civ.impliedVolatility ,callPrice= ltp)
				if flag == "price":
					return cval.callPrice
				if flag == "delta":
					return cval.callDelta
				if flag == "delta2":
					return cval.callDelta2
				if flag == "theta":
					return cval.callTheta
				if flag == "rho":
					return cval.callRho
				if flag == "vega":
					return cval.vega
				if flag == "gamma":
					return cval.gamma
				if flag == "all_val":
					return {'callPrice' : cval.callPrice, 'callDelta' : cval.callDelta, 'callDelta2' : cval.callDelta2, 'callTheta' : cval.callTheta, 'callRho' : cval.callRho, 'vega' : cval.vega, 'gamma' : cval.gamma}

			if scrip_type == "PE":
				piv = mibian.BS([asset_price, strike, interest_rate, days_to_expiry], putPrice= ltp)
				pval = mibian.BS([asset_price, strike, interest_rate, days_to_expiry], volatility = piv.impliedVolatility ,putPrice= ltp)
				if flag == "price":
					return pval.putPrice
				if flag == "delta":
					return pval.putDelta
				if flag == "delta2":
					return pval.putDelta2
				if flag == "theta":
					return pval.putTheta
				if flag == "rho":
					return pval.putRho
				if flag == "vega":
					return pval.vega
				if flag == "gamma":
					return pval.gamma
				if flag == "all_val":
					return {'callPrice' : pval.putPrice, 'callDelta' : pval.putDelta, 'callDelta2' : pval.putDelta2, 'callTheta' : pval.putTheta, 'callRho' : pval.putRho, 'vega' : pval.vega, 'gamma' : pval.gamma}

		except Exception as e:
			print(f"Exception in get_option_greek: {e}")
			return None


	def get_expiry_list(self, Underlying, exchange):
		try:
			Underlying = Underlying.upper()
			exchange = exchange.upper()
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			exchange_segment = script_exchange[exchange]
			index_exchange = {"NIFTY":'NSE',"BANKNIFTY":"NSE","FINNIFTY":"NSE","MIDCPNIFTY":"NSE","BANKEX":"BSE","SENSEX":"BSE"}
			if Underlying in index_exchange:
				exchange =index_exchange[Underlying]

			if Underlying in self.commodity_step_dict.keys():
				security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==Underlying.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
				if security_check.empty:
					raise Exception("Check the Tradingsymbol")
				security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
			else:						
				security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
				if security_check.empty:
					raise Exception("Check the Tradingsymbol")
				security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']

			response = self.Dhan.expiry_list(under_security_id =int(security_id), under_exchange_segment = exchange_segment)
			if response['status']=='success':
				return response['data']['data']
			else:
				raise Exception(response)
		except Exception as e:
			print(f"Exception at getting Expiry list as {e}")
			return list()
		
	# def get_option_chain(self, Underlying, exchange, expiry):
		try:
			Underlying = Underlying.upper()
			exchange = exchange.upper()
			script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
			instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
			exchange_segment = script_exchange[exchange]
			index_exchange = {"NIFTY":'NSE',"BANKNIFTY":"NSE","FINNIFTY":"NSE","MIDCPNIFTY":"NSE","BANKEX":"BSE","SENSEX":"BSE"}
			
			if Underlying in index_exchange:
				exchange =index_exchange[Underlying]

			if Underlying in self.commodity_step_dict.keys():
				security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==Underlying.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
				if security_check.empty:
					raise Exception("Check the Tradingsymbol")
				security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
			else:						
				security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
				if security_check.empty:
					raise Exception("Check the Tradingsymbol")
				security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']

			if Underlying in index_exchange:
				expiry_exchange = 'INDEX'
			elif Underlying in self.commodity_step_dict.keys():
				exchange = "MCX"
				expiry_exchange = exchange
			else:
				# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
				exchange = "NSE"
				expiry_exchange = exchange

			expiry_list = self.get_expiry_list(Underlying=Underlying, exchange = expiry_exchange)

			if len(expiry_list)==0:
				print(f"Unable to find the correct Expiry for {Underlying}")
				return None
			if len(expiry_list)<expiry:
				Expiry_date = expiry_list[-1]
			else:
				Expiry_date = expiry_list[expiry]						

			# time.sleep(3)
			response = self.Dhan.option_chain(under_security_id =int(security_id), under_exchange_segment = exchange_segment, expiry = Expiry_date)
			if response['status']=='success':
				oc = response['data']['data']
				oc_df = self.format_option_chain(oc)
				return oc_df
			else:
				raise Exception(response)			
		except Exception as e:
			print(f"Getting Error at Option Chain as {e}")	


	def format_option_chain(self,data):
		"""
		Formats JSON data into an Option Chain structure with the Strike Price column in the middle.
		
		Args:
			data (dict): The JSON data containing option chain details.
		
		Returns:
			pd.DataFrame: Formatted DataFrame of the option chain.
		"""
		try:
			# Extract and structure the data
			option_chain_rows = []
			for strike, details in data["oc"].items():
				ce = details.get("ce", {})
				pe = details.get("pe", {})
				ce_greeks = ce.get("greeks", {})
				pe_greeks = pe.get("greeks", {})
				
				option_chain_rows.append({
					# Calls (CE) data
					"CE OI": ce.get("oi", None),
					"CE Chg in OI": ce.get("oi", 0) - ce.get("previous_oi", 0),
					"CE Volume": ce.get("volume", None),
					"CE IV": ce.get("implied_volatility", None),
					"CE LTP": ce.get("last_price", None),
					"CE Bid Qty": ce.get("top_bid_quantity", None),
					"CE Bid": ce.get("top_bid_price", None),
					"CE Ask": ce.get("top_ask_price", None),
					"CE Ask Qty": ce.get("top_ask_quantity", None),
					"CE Delta": ce_greeks.get("delta", None),
					"CE Theta": ce_greeks.get("theta", None),
					"CE Gamma": ce_greeks.get("gamma", None),
					"CE Vega": ce_greeks.get("vega", None),
					# Strike Price
					"Strike Price": strike,
					# Puts (PE) data
					"PE Bid Qty": pe.get("top_bid_quantity", None),
					"PE Bid": pe.get("top_bid_price", None),
					"PE Ask": pe.get("top_ask_price", None),
					"PE Ask Qty": pe.get("top_ask_quantity", None),
					"PE LTP": pe.get("last_price", None),
					"PE IV": pe.get("implied_volatility", None),
					"PE Volume": pe.get("volume", None),
					"PE Chg in OI": pe.get("oi", 0) - pe.get("previous_oi", 0),
					"PE OI": pe.get("oi", None),
					"PE Delta": pe_greeks.get("delta", None),
					"PE Theta": pe_greeks.get("theta", None),
					"PE Gamma": pe_greeks.get("gamma", None),
					"PE Vega": pe_greeks.get("vega", None),
				})
			
			# Create a DataFrame
			df = pd.DataFrame(option_chain_rows)
			
			# Move "Strike Price" to the middle
			columns = list(df.columns)
			strike_index = columns.index("Strike Price")
			new_order = columns[:strike_index] + columns[strike_index + 1:]
			middle_index = len(new_order) // 2
			new_order = new_order[:middle_index] + ["Strike Price"] + new_order[middle_index:]
			df = df[new_order]
			
			return df
		except Exception as e:
			print(f"Unable to form the Option chain as {e}")
			return data
	

	def send_telegram_alert(self,message, receiver_chat_id, bot_token):
		"""
		Sends a message via Telegram bot to a specific chat ID.
		
		Parameters:
			message (str): The message to be sent.
			receiver_chat_id (str): The chat ID of the receiver.
			bot_token (str): The token of the Telegram bot.
		"""
		try:
			encoded_message = urllib.parse.quote(message)
			send_text = f'https://api.telegram.org/bot{bot_token}/sendMessage?chat_id={receiver_chat_id}&text={encoded_message}'
			response = requests.get(send_text)
			response.raise_for_status()
			if int(response.status_code) ==200:
				print(f"Message sent successfully")
			else:
				raise Exception(response.json())
		except requests.exceptions.RequestException as e:
			print(f"Failed to send message: {e}")



	def heikin_ashi(self, df):
		try:
			if df.empty:
				raise ValueError("Input DataFrame is empty.")
			
			# Ensure the DataFrame has the required columns
			required_columns = ['open', 'high', 'low', 'close', 'timestamp']
			if not all(col in df.columns for col in required_columns):
				raise ValueError(f"Input DataFrame must contain these columns: {required_columns}")

			# Prepare Heikin-Ashi columns
			ha_close = (df['open'] + df['high'] + df['low'] + df['close']) / 4
			ha_open = [df['open'].iloc[0]]  # Initialize the first open value
			ha_high = []
			ha_low = []

			# Compute Heikin-Ashi values
			for i in range(1, len(df)):
				ha_open.append((ha_open[-1] + ha_close.iloc[i - 1]) / 2)
				ha_high.append(max(df['high'].iloc[i], ha_open[-1], ha_close.iloc[i]))
				ha_low.append(min(df['low'].iloc[i], ha_open[-1], ha_close.iloc[i]))

			# Append first values for high and low
			ha_high.insert(0, df['high'].iloc[0])
			ha_low.insert(0, df['low'].iloc[0])

			# Create a new DataFrame for Heikin-Ashi values
			ha_df = pd.DataFrame({
				'timestamp': df['timestamp'],
				'open': ha_open,
				'high': ha_high,
				'low': ha_low,
				'close': ha_close
			})

			return ha_df
		except Exception as e:
			self.logger.exception(f"Error in Heikin-Ashi calculation: {e}")
			pass
			# return pd.DataFrame()


	def renko_bricks(self,data, box_size=7):
		renko_data = []
		current_brick_color = None
		prev_close = None

		for _, row in data.iterrows():
			open_price, close_price = row['open'], row['close']

			if prev_close is None:
				prev_close = (open_price//box_size)*box_size

			while abs(close_price - prev_close) >= box_size:
				price_diff = close_price - prev_close
				
				if price_diff > 0:
					if current_brick_color == 'red':
						# Switching from red to green requires at least 2 * box_size move
						if price_diff < 2 * box_size:
							break
						prev_close += 2 * box_size  # Ensures correct switch
					else:
						prev_close += box_size
					
					current_brick_color = 'green'

				elif price_diff < 0:
					if current_brick_color == 'green':
						# Switching from green to red requires at least 2 * box_size move
						if -price_diff < 2 * box_size:
							break
						prev_close -= 2 * box_size  # Ensures correct switch
					else:
						prev_close -= box_size
					
					current_brick_color = 'red'
				
				renko_data.append({
					'timestamp': row['timestamp'],
					'open': prev_close - box_size if current_brick_color == 'green' else prev_close + box_size,
					'high': prev_close if current_brick_color == 'green' else prev_close + box_size,
					'low': prev_close - box_size if current_brick_color == 'red' else prev_close,
					'close': prev_close,
					'brick_color': current_brick_color,
				})

		return pd.DataFrame(renko_data)



	def get_option_chain(self, Underlying, exchange, expiry,num_strikes):
			try:
				# pdb.set_trace()
				Underlying = Underlying.upper()
				exchange = exchange.upper()
				script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
				instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
				exchange_segment = script_exchange[exchange]
				index_exchange = {"NIFTY":'NSE',"BANKNIFTY":"NSE","FINNIFTY":"NSE","MIDCPNIFTY":"NSE","BANKEX":"BSE","SENSEX":"BSE"}
				
				if Underlying in index_exchange:
					exchange =index_exchange[Underlying]

				if Underlying in self.commodity_step_dict.keys():
					security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==Underlying.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]                        
					if security_check.empty:
						raise Exception("Check the Tradingsymbol")
					security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
				else:                       
					security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
					if security_check.empty:
						raise Exception("Check the Tradingsymbol")
					security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']

				if Underlying in index_exchange:
					expiry_exchange = 'INDEX'
				elif Underlying in self.commodity_step_dict.keys():
					exchange = "MCX"
					expiry_exchange = exchange
				else:
					# exchange = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==Underlying)|(instrument_df['SEM_CUSTOM_SYMBOL']==Underlying))].iloc[0]['SEM_EXM_EXCH_ID']
					exchange = "NSE"
					expiry_exchange = exchange

				expiry_list = self.get_expiry_list(Underlying=Underlying, exchange = expiry_exchange)

				if len(expiry_list)==0:
					print(f"Unable to find the correct Expiry for {Underlying}")
					return None
				if len(expiry_list)<expiry:
					Expiry_date = expiry_list[-1]
				else:
					Expiry_date = expiry_list[expiry]                       

				# time.sleep(3)
				response = self.Dhan.option_chain(under_security_id =int(security_id), under_exchange_segment = exchange_segment, expiry = Expiry_date)
				if response['status']=='success':
					oc = response['data']['data']
					oc_df = self.format_option_chain(oc)
					# pdb.set_trace()

					atm_price = self.get_ltp_data(Underlying)
					oc_df['Strike Price'] = pd.to_numeric(oc_df['Strike Price'], errors='coerce')
					# strike_step = self.stock_step_df[Underlying]
					if Underlying in self.index_step_dict:
						strike_step = self.index_step_dict[Underlying]
					elif Underlying in self.stock_step_df:
						strike_step = self.stock_step_df[Underlying]
					else:
						raise Exception(f"No option chain data available for the {Underlying}")
					# pdb.set_trace()
					# atm_strike = oc_df.loc[(oc_df['Strike Price'] - atm_price[Underlying]).abs().idxmin(), 'Strike Price']
					atm_strike = round(atm_price[Underlying]/strike_step) * strike_step

					df = oc_df[(oc_df['Strike Price'] >= atm_strike - num_strikes * strike_step) & (oc_df['Strike Price'] <= atm_strike + num_strikes * strike_step)].sort_values(by='Strike Price').reset_index(drop=True)
					return atm_strike, df
				else:
					raise Exception(response)           
			except Exception as e:
				print(f"Getting Error at Option Chain as {e}")




	def margin_calculator(self, tradingsymbol, exchange, transaction_type, quantity, trade_type, price, trigger_price=0):
			try:

				tradingsymbol = tradingsymbol.upper()
				exchange = exchange.upper()
				instrument_df = self.instrument_df.copy()
				script_exchange = {"NSE":self.Dhan.NSE, "NFO":self.Dhan.FNO, "BFO":"BSE_FNO", "CUR": self.Dhan.CUR, "BSE":self.Dhan.BSE, "MCX":self.Dhan.MCX, "INDEX":self.Dhan.INDEX}
				instrument_exchange = {'NSE':"NSE",'BSE':"BSE",'NFO':'NSE','BFO':'BSE','MCX':'MCX','CUR':'NSE'}
				exchange_segment = script_exchange[exchange]
				product = {'MIS':self.Dhan.INTRA, 'MARGIN':self.Dhan.MARGIN, 'MTF':self.Dhan.MTF, 'CO':self.Dhan.CO,'BO':self.Dhan.BO, 'CNC': self.Dhan.CNC}
				transactiontype = {'BUY': self.Dhan.BUY, 'SELL': self.Dhan.SELL}			
				
				product_Type = product[trade_type.upper()]
				order_side = transactiontype[transaction_type.upper()]

				security_check = instrument_df[((instrument_df['SEM_TRADING_SYMBOL']==tradingsymbol)|(instrument_df['SEM_CUSTOM_SYMBOL']==tradingsymbol))&(instrument_df['SEM_EXM_EXCH_ID']==instrument_exchange[exchange])]
				if security_check.empty:
					raise Exception("Check the Tradingsymbol")
				security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']

				response = self.Dhan.margin_calculator(str(security_id), exchange_segment, order_side, int(quantity), product_Type, float(price), float(trigger_price))
				if response['status']=='success':
					oc = response['data']
					return oc
				else:
					raise Exception(response)					
			except Exception as e:
				print(f"Error at getting response from msrgin calculator as {e}")


	def get_quote(self,names, debug="NO"):
			try:
				instrument_df = self.instrument_df.copy()
				instruments = {'NSE_EQ':[],'IDX_I':[],'NSE_FNO':[],'NSE_CURRENCY':[],'BSE_EQ':[],'BSE_FNO':[],'BSE_CURRENCY':[],'MCX_COMM':[]}
				instrument_names = {}
				NFO = ["BANKNIFTY","NIFTY","MIDCPNIFTY","FINNIFTY"]
				BFO = ['SENSEX','BANKEX']
				equity = ['CALL','PUT','FUT']			
				exchange_index = {"BANKNIFTY": "NSE_IDX","NIFTY":"NSE_IDX","MIDCPNIFTY":"NSE_IDX", "FINNIFTY":"NSE_IDX","SENSEX":"BSE_IDX","BANKEX":"BSE_IDX"}
				if not isinstance(names, list):
					names = [names]
				for name in names:
					try:
						name = name.upper()
						if name in exchange_index.keys():
							security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))]
							if security_check.empty:
								raise Exception("Check the Tradingsymbol")
							security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
							instruments['IDX_I'].append(int(security_id))
							instrument_names[str(security_id)]=name
						elif name in self.commodity_step_dict.keys():
							security_check = instrument_df[(instrument_df['SEM_EXM_EXCH_ID']=='MCX')&(instrument_df['SM_SYMBOL_NAME']==name.upper())&(instrument_df['SEM_INSTRUMENT_NAME']=='FUTCOM')]						
							if security_check.empty:
								raise Exception("Check the Tradingsymbol")
							security_id = security_check.sort_values(by='SEM_EXPIRY_DATE').iloc[0]['SEM_SMST_SECURITY_ID']
							instruments['MCX_COMM'].append(int(security_id))
							instrument_names[str(security_id)]=name
						else:
							security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))]
							if security_check.empty:
								raise Exception("Check the Tradingsymbol")						
							security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
							nfo_check = ['NSE_FNO' for nfo in NFO if nfo in name]
							bfo_check = ['BSE_FNO' for bfo in BFO if bfo in name]
							exchange_nfo ='NSE_FNO' if len(nfo_check)!=0 else False
							exchange_bfo = 'BSE_FNO' if len(bfo_check)!=0 else False
							if not exchange_nfo and not exchange_bfo:
								eq_check =['NSE_FNO' for nfo in equity if nfo in name]
								exchange_eq ='NSE_FNO' if len(eq_check)!=0 else "NSE_EQ"
							else:
								exchange_eq="NSE_EQ"
							exchange ='NSE_FNO' if exchange_nfo else ('BSE_FNO' if exchange_bfo else exchange_eq)
							trail_exchange = exchange
							mcx_check = ['MCX_COMM' for mcx in self.commodity_step_dict.keys() if mcx in name]
							exchange = "MCX_COMM" if len(mcx_check)!=0 else exchange
							if exchange == "MCX_COMM": 
								if instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))&(instrument_df['SEM_EXM_EXCH_ID']=='MCX')].empty:
									exchange = trail_exchange
							if exchange == "MCX_COMM":
								security_check = instrument_df[((instrument_df['SEM_CUSTOM_SYMBOL']==name)|(instrument_df['SEM_TRADING_SYMBOL']==name))&(instrument_df['SEM_EXM_EXCH_ID']=='MCX')]
								if security_check.empty:
									raise Exception("Check the Tradingsymbol")	
								security_id = security_check.iloc[-1]['SEM_SMST_SECURITY_ID']
							instruments[exchange].append(int(security_id))
							instrument_names[str(security_id)]=name
					except Exception as e:
						print(f"Exception for instrument name {name} as {e}")
				time.sleep(2)
				data = self.Dhan.quote_data(instruments)
				ltp_data=dict()

				if debug.upper()=="YES":
					print(data)			

				if data['status']!='failure':
					all_values = data['data']['data']
					for exchange in data['data']['data']:
						for key, values in all_values[exchange].items():
							symbol = instrument_names[key]
							ltp_data[symbol] = values
				else:
					raise Exception(data)
				
				return ltp_data
			except Exception as e:
				print(f"Exception at calling quote data as {e}")
				self.logger.exception(f"Exception at calling ltp as {e}")
				return dict()

	def format_pnl_report(self, holdings_response: dict, positions_response: dict):
		holdings = self.unwrap_sdk_data(holdings_response)
		positions = self.unwrap_sdk_data(positions_response)
		report = {'total_investment': 0.0, 'current_value': 0.0, 'total_pnl': 0.0, 'day_pnl': 0.0, 'holdings_count': len(holdings or []), 'positions_count': len(positions or [])}
		for holding in holdings or []:
			total_qty = holding.get('totalQty', 0)
			report['total_investment'] += holding.get('avgCostPrice', 0) * total_qty
			report['current_value'] += holding.get('marketValue', 0)
			report['total_pnl'] += holding.get('pnl', 0)
			report['day_pnl'] += holding.get('dayPnl', 0)
		for position in positions or []:
			report['total_pnl'] += position.get('realizedProfit', 0) + position.get('unrealizedProfit', 0)
		return report

	def get_portfolio_summary(self):
		holdings_resp = self.Dhan.get_holdings()
		positions_resp = self.Dhan.get_positions()
		funds_resp = self.Dhan.get_fund_limits()
		trades_resp = self.Dhan.get_trade_book()
		return {
			'holdings': self.unwrap_sdk_data(holdings_resp),
			'positions': self.unwrap_sdk_data(positions_resp),
			'funds': self.unwrap_sdk_data(funds_resp),
			'trades': self.unwrap_sdk_data(trades_resp),
			'summary': self.format_pnl_report(holdings_resp, positions_resp),
		}

	def get_history_df(self, security_id: str, exchange_segment: str, instrument_type: str, from_date: str, to_date: str, interval: str = 'daily'):
		if interval.lower() == 'daily':
			response = self.Dhan.historical_daily_data(security_id=security_id, exchange_segment=exchange_segment, instrument_type=instrument_type, from_date=from_date, to_date=to_date)
		else:
			response = self.Dhan.intraday_minute_data(security_id=security_id, exchange_segment=exchange_segment, instrument_type=instrument_type, from_date=from_date, to_date=to_date, interval=interval)
		data = self.unwrap_sdk_data(response)
		df = pd.DataFrame(data)
		if 'timestamp' in df.columns:
			df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s', utc=True).dt.tz_convert('Asia/Kolkata')
		return df

	def add_basic_indicators(self, df: pd.DataFrame, fast_sma: int = 20, slow_sma: int = 50):
		output = df.copy()
		if 'close' not in output.columns:
			return output
		output[f'SMA_{fast_sma}'] = output['close'].rolling(fast_sma).mean()
		output[f'SMA_{slow_sma}'] = output['close'].rolling(slow_sma).mean()
		output['returns'] = output['close'].pct_change()
		return output

	def place_forever_order(self, security_id: str, exchange_segment: str, transaction_type: str, product_type: str, order_type: str, quantity: int, price: float, trigger_price: float, order_flag: str = 'SINGLE', price1: float = None, trigger_price1: float = None, validity: str = 'DAY', tag: str = None):
		payload = {
			'security_id': security_id,
			'exchange_segment': exchange_segment,
			'transaction_type': transaction_type,
			'product_type': product_type,
			'order_type': order_type,
			'quantity': quantity,
			'price': price,
			'trigger_Price': trigger_price,
			'order_flag': order_flag,
			'validity': validity,
		}
		if price1 is not None:
			payload['price1'] = price1
		if trigger_price1 is not None:
			payload['trigger_Price1'] = trigger_price1
		if tag is not None:
			payload['tag'] = tag
		return self.Dhan.place_forever(**payload)

	def get_forever_orders(self):
		return self.Dhan.get_forever()

	def cancel_forever_order(self, order_id: str):
		return self.Dhan.cancel_forever(order_id=order_id)

	def place_super_order(self, security_id: str, exchange_segment: str, transaction_type: str, quantity: int, order_type: str, product_type: str, price: float, target_price: float, stop_loss_price: float, trailing_jump: float = None, tag: str = None):
		payload = {
			'security_id': security_id,
			'exchange_segment': exchange_segment,
			'transaction_type': transaction_type,
			'quantity': quantity,
			'order_type': order_type,
			'product_type': product_type,
			'price': price,
			'targetPrice': target_price,
			'stopLossPrice': stop_loss_price,
		}
		if trailing_jump is not None:
			payload['trailingJump'] = trailing_jump
		if tag is not None:
			payload['tag'] = tag
		return self.Dhan.place_super_order(**payload)

	def modify_super_order(self, order_id: str, **kwargs):
		return self.Dhan.modify_super_order(order_id=order_id, **kwargs)

	def cancel_super_order(self, order_id: str):
		return self.Dhan.cancel_super_order(order_id=order_id)

	def get_super_orders(self):
		return self.Dhan.get_super_order_list()

	def convert_position(self, security_id: str, exchange_segment: str, transaction_type: str, position_type: str, quantity: int, old_product_type: str, new_product_type: str):
		return self.Dhan.convert_position(security_id=security_id, exchange_segment=exchange_segment, transaction_type=transaction_type, position_type=position_type, quantity=quantity, old_product_type=old_product_type, new_product_type=new_product_type)

	def create_market_feed(self, instruments, version: str = 'v2', on_connect=None, on_message=None, on_close=None):
		if MarketFeed is None or self.dhan_context is None:
			raise ValueError('MarketFeed requires a DhanContext-compatible SDK installation.')
		return MarketFeed(self.dhan_context, instruments, version, on_connect=on_connect, on_message=on_message, on_close=on_close)

	def create_order_update_feed(self, on_update=None):
		if OrderUpdate is None or self.dhan_context is None:
			raise ValueError('OrderUpdate requires a DhanContext-compatible SDK installation.')
		feed = OrderUpdate(self.dhan_context)
		if on_update is not None:
			feed.on_update = on_update
		return feed

	def get_expiry_dates(self, under_security_id: int, under_exchange_segment: str = 'IDX_I'):
		response = self.Dhan.expiry_list(under_security_id=under_security_id, under_exchange_segment=under_exchange_segment)
		return self.unwrap_sdk_data(response)

	def build_option_legs(self, chain_df: pd.DataFrame, legs_config: list):
		legs = []
		for config in legs_config:
			strike = float(config['strike'])
			right = config['right'].lower()
			row_match = chain_df[chain_df['strike'] == strike]
			if row_match.empty:
				raise ValueError(f'Strike {strike} not found in option chain')
			row = row_match.iloc[0]
			prefix = 'ce' if right == 'ce' else 'pe'
			legs.append({'label': config.get('label', f"{config['action']} {int(strike)} {right.upper()}"), 'action': config['action'].upper(), 'right': right.upper(), 'strike': strike, 'premium': float(row[f'{prefix}_ltp']), 'security_id': row[f'{prefix}_security_id'], 'lots': int(config.get('lots', 1))})
		return legs

	def option_payoff(self, spot_range, legs: list, lot_size: int):
		payoff = np.zeros_like(spot_range, dtype=float)
		for leg in legs:
			if leg['right'] == 'CE':
				intrinsic = np.maximum(spot_range - leg['strike'], 0)
			else:
				intrinsic = np.maximum(leg['strike'] - spot_range, 0)
			qty_sign = 1 if leg['action'] == 'BUY' else -1
			payoff += (intrinsic - leg['premium']) * qty_sign * leg['lots'] * lot_size
		return payoff

	def analyze_iron_condor(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, wing_width: int = 200, short_offset: int = 200, lot_size: int = None):
		if expiry is None:
			expiry = self.get_expiry_dates(under_security_id)[0]
		chain_df, spot = self.fetch_option_chain_df(under_security_id=under_security_id, expiry=expiry)
		strike_prices = sorted(chain_df['strike'].tolist())
		sell_ce_strike = min(strike_prices, key=lambda value: abs(value - (spot + short_offset)))
		buy_ce_strike = sell_ce_strike + wing_width
		sell_pe_strike = min(strike_prices, key=lambda value: abs(value - (spot - short_offset)))
		buy_pe_strike = sell_pe_strike - wing_width
		legs = self.build_option_legs(chain_df, [
			{'action': 'SELL', 'right': 'PE', 'strike': sell_pe_strike, 'label': f'Sell {int(sell_pe_strike)} PE'},
			{'action': 'BUY', 'right': 'PE', 'strike': buy_pe_strike, 'label': f'Buy {int(buy_pe_strike)} PE'},
			{'action': 'SELL', 'right': 'CE', 'strike': sell_ce_strike, 'label': f'Sell {int(sell_ce_strike)} CE'},
			{'action': 'BUY', 'right': 'CE', 'strike': buy_ce_strike, 'label': f'Buy {int(buy_ce_strike)} CE'},
		])
		lot_size = lot_size or self.get_lot_size_from_master(underlying=underlying) or 1
		spot_range = np.arange(spot - 1000, spot + 1000, 10)
		payoff = self.option_payoff(spot_range, legs, lot_size)
		sign_changes = np.where(np.diff(np.sign(payoff)))[0]
		breakevens = spot_range[sign_changes].tolist()
		return {'underlying': underlying, 'expiry': expiry, 'spot': spot, 'legs': legs, 'lot_size': lot_size, 'max_profit': float(payoff.max()), 'max_loss': float(payoff.min()), 'breakevens': breakevens, 'payoff_points': {'spot_range': spot_range.tolist(), 'payoff': payoff.tolist()}}

	def get_atm_option_pair(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, under_exchange_segment: str = 'IDX_I'):
		if expiry is None:
			expiry = self.get_expiry_dates(under_security_id, under_exchange_segment)[0]
		chain_df, spot = self.fetch_option_chain_df(under_security_id=under_security_id, expiry=expiry, under_exchange_segment=under_exchange_segment)
		atm = self.find_atm_row(chain_df, spot)
		lot_size = self.get_lot_size_from_master(underlying=underlying)
		return {'underlying': underlying, 'expiry': expiry, 'spot': spot, 'strike': float(atm['strike']), 'call_security_id': atm['ce_security_id'], 'call_price': float(atm['ce_ltp']), 'put_security_id': atm['pe_security_id'], 'put_price': float(atm['pe_ltp']), 'lot_size': lot_size}

	def prepare_equity_limit_order(self, symbol: str, price: float, quantity: int, transaction_type: str = 'BUY', product_type: str = 'INTRADAY', exchange_segment: str = 'NSE_EQ'):
		resolved = self.resolve_symbol(symbol, exchange_segment=exchange_segment, instrument_name='EQUITY')
		if resolved is None:
			raise ValueError(f'Unable to resolve symbol {symbol}')
		validation = self.validate_order_payload(security_id=resolved['security_id'], exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, order_type='LIMIT', product_type=product_type, price=price, trading_symbol=resolved['trading_symbol'])
		return {'instrument': resolved, 'validation': validation, 'preview': self.preview_order(security_id=resolved['security_id'], exchange_segment=exchange_segment, transaction_type=transaction_type, quantity=quantity, order_type='LIMIT', product_type=product_type, price=price, trading_symbol=resolved['trading_symbol'])}

	def get_option_chain_snapshot(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, under_exchange_segment: str = 'IDX_I', points_each_side: int = 500):
		if expiry is None:
			expiry = self.get_expiry_dates(under_security_id, under_exchange_segment)[0]
		chain_df, spot = self.fetch_option_chain_df(under_security_id=under_security_id, expiry=expiry, under_exchange_segment=under_exchange_segment)
		atm = self.find_atm_row(chain_df, spot)
		view = chain_df[['strike', 'ce_ltp', 'ce_oi', 'ce_iv', 'pe_ltp', 'pe_oi', 'pe_iv']].copy()
		nearby = view[(view['strike'] >= atm['strike'] - points_each_side) & (view['strike'] <= atm['strike'] + points_each_side)].reset_index(drop=True)
		return {'underlying': underlying, 'expiry': expiry, 'spot': spot, 'atm_strike': float(atm['strike']), 'chain': nearby}

	def check_margin_for_orders(self, orders: list):
		results = []
		total_margin = 0.0
		available_balance = None
		for order in orders:
			margin = self.check_margin_requirement(security_id=str(order['security_id']), exchange_segment=order['exchange_segment'], transaction_type=order['transaction_type'], quantity=int(order['quantity']), product_type=order['product_type'], price=float(order.get('price', 0) or 0), trigger_price=float(order.get('trigger_price', 0) or 0))
			results.append({'order': order, 'margin': margin})
			total_margin += float(margin.get('total_margin', 0) or 0)
			if available_balance is None:
				available_balance = margin.get('available_balance', 0.0)
		return {'orders': results, 'total_margin': total_margin, 'available_balance': available_balance or 0.0, 'sufficient': (available_balance or 0.0) >= total_margin, 'shortfall': max(0.0, total_margin - (available_balance or 0.0))}

	def place_multi_leg_orders(self, orders: list, dry_run: bool = True, continue_on_error: bool = False):
		results = []
		for order in orders:
			result = self.place_order(symbol=order.get('symbol'), security_id=order.get('security_id'), exchange_segment=order.get('exchange_segment', 'NSE_FNO'), transaction_type=order.get('transaction_type', 'BUY'), quantity=order.get('quantity', 1), order_type=order.get('order_type', 'LIMIT'), product_type=order.get('product_type', 'INTRADAY'), price=order.get('price', 0), trigger_price=order.get('trigger_price', 0), validity=order.get('validity', 'DAY'), disclosed_quantity=order.get('disclosed_quantity', 0), after_market_order=order.get('after_market_order', False), amo_time=order.get('amo_time', 'OPEN'), tag=order.get('tag'), lot_size=order.get('lot_size'), instrument_name=order.get('instrument_name', 'OPTIDX'), dry_run=dry_run)
			results.append(result)
			if not dry_run:
				response = result.get('response', {})
				if response.get('status') == 'failure' and not continue_on_error:
					break
		return {'dry_run': dry_run, 'orders': results}

	def place_long_call(self, underlying: str = 'NIFTY', expiry: str = None, strike: float = None, under_security_id: int = 13, quantity: int = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', exchange: str = 'NSE', dry_run: bool = True):
		if strike is None:
			atm_pair = self.get_atm_option_pair(underlying=underlying, under_security_id=under_security_id, expiry=expiry)
			strike = atm_pair['strike']
			if expiry is None:
				expiry = atm_pair['expiry']
		return self.place_option_order(underlying=underlying, expiry=expiry, strike=strike, option_type='CE', quantity=quantity, transaction_type='BUY', order_type=order_type, product_type=product_type, price=0, exchange=exchange, dry_run=dry_run)

	def place_long_put(self, underlying: str = 'NIFTY', expiry: str = None, strike: float = None, under_security_id: int = 13, quantity: int = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', exchange: str = 'NSE', dry_run: bool = True):
		if strike is None:
			atm_pair = self.get_atm_option_pair(underlying=underlying, under_security_id=under_security_id, expiry=expiry)
			strike = atm_pair['strike']
			if expiry is None:
				expiry = atm_pair['expiry']
		return self.place_option_order(underlying=underlying, expiry=expiry, strike=strike, option_type='PE', quantity=quantity, transaction_type='BUY', order_type=order_type, product_type=product_type, price=0, exchange=exchange, dry_run=dry_run)

	def buy_call_put_pair(self, underlying: str = 'NIFTY', expiry: str = None, call_strike: float = None, put_strike: float = None, under_security_id: int = 13, quantity: int = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', exchange: str = 'NSE', dry_run: bool = True):
		atm_pair = self.get_atm_option_pair(underlying=underlying, under_security_id=under_security_id, expiry=expiry)
		expiry = expiry or atm_pair['expiry']
		call_strike = float(call_strike if call_strike is not None else atm_pair['strike'])
		put_strike = float(put_strike if put_strike is not None else atm_pair['strike'])
		call_order = self.place_option_order(underlying=underlying, expiry=expiry, strike=call_strike, option_type='CE', quantity=quantity, transaction_type='BUY', order_type=order_type, product_type=product_type, price=0, exchange=exchange, dry_run=dry_run)
		put_order = self.place_option_order(underlying=underlying, expiry=expiry, strike=put_strike, option_type='PE', quantity=quantity, transaction_type='BUY', order_type=order_type, product_type=product_type, price=0, exchange=exchange, dry_run=dry_run)
		return {'strategy': 'CALL_PUT_PAIR', 'underlying': underlying, 'expiry': expiry, 'call_strike': call_strike, 'put_strike': put_strike, 'call_order': call_order, 'put_order': put_order}

	def build_iron_condor_orders(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, wing_width: int = 200, short_offset: int = 200, quantity: int = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT'):
		analysis = self.analyze_iron_condor(underlying=underlying, under_security_id=under_security_id, expiry=expiry, wing_width=wing_width, short_offset=short_offset, lot_size=quantity)
		effective_qty = quantity or analysis['lot_size'] or 1
		orders = []
		for leg in analysis['legs']:
			orders.append({'symbol': leg['label'], 'security_id': leg['security_id'], 'exchange_segment': 'NSE_FNO', 'transaction_type': leg['action'], 'quantity': effective_qty * int(leg.get('lots', 1)), 'order_type': order_type, 'product_type': product_type, 'price': float(leg['premium']), 'instrument_name': 'OPTIDX', 'lot_size': analysis['lot_size']})
		return {'analysis': analysis, 'orders': orders}

	def place_iron_condor(self, underlying: str = 'NIFTY', under_security_id: int = 13, expiry: str = None, wing_width: int = 200, short_offset: int = 200, quantity: int = None, product_type: str = 'INTRADAY', order_type: str = 'LIMIT', dry_run: bool = True, continue_on_error: bool = False):
		payload = self.build_iron_condor_orders(underlying=underlying, under_security_id=under_security_id, expiry=expiry, wing_width=wing_width, short_offset=short_offset, quantity=quantity, product_type=product_type, order_type=order_type)
		margin = self.check_margin_for_orders(payload['orders'])
		placements = self.place_multi_leg_orders(payload['orders'], dry_run=dry_run, continue_on_error=continue_on_error)
		return {'strategy': 'IRON_CONDOR', 'analysis': payload['analysis'], 'margin': margin, 'placements': placements}




