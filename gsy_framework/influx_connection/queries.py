from gsy_framework.influx_connection.connection import InfluxConnection
from gsy_framework.constants_limits import GlobalConfig
from pendulum import duration
import pandas as pd
import os
import pathlib

# abstract base query class
class Query:
    def __init__(self, influxConnection: InfluxConnection, duration, start, interval):
        self.connection = influxConnection
        self._set_time(duration, start, interval)
        self.query_string()

    def _set_time(self, duration, start, interval):
        self.duration = duration
        self.start = start
        self.interval = interval
        self.end = self.start + self.duration

    def update_query(self, duration, start, interval):
        self._set_time(duration, start, interval)
        self.query_string()
    
    #executes query
    def exec(self):
        self.qresults = self.connection.query(self.qstring)
        return self.transform()

    def get_query_string(self):
        return self.qstring
    
    # defines query string: overwrite this class
    def query_string(self):
        self.qstring = ""

    # transforms results of query to dict class, that gets returned: overwrite this class
    def transform(self):
        return self.qresults


# raw query class (overwriting query string and transformation fucntion with a provided one)
class RawQuery(Query):
    def __init__(self, influxConnection: InfluxConnection, querystring: str, trans_func):
        super().__init__(influxConnection)
        self.qstring = querystring
        self.procFunc = procFunc

    def exec(self):
        qresults = super().exec()
        return self.procFunc(qresults)


# abstract class for data from single meter
class DataQuery(Query):
    def __init__(self, 
                influxConnection: InfluxConnection, duration, start, interval, multiplier):
        self.multiplier = multiplier
        super().__init__(influxConnection, duration, start, interval)

    def transform(self):
        # Get DataFrame from result
        if(len(list(self.qresults.values())) != 1):
            print("Load Profile for Query:\n" + self.qstring + "\nnot valid. Using Zero Curve.")
            return os.path.join(pathlib.Path(__file__).parent.resolve(), "resources", "Zero_Curve.csv")
            

        df = list(self.qresults.values())[0]

        df = df.reset_index(level=0)

        # remove day from time data
        df["index"] = df["index"].map(lambda x: x.strftime("%H:%M"))

        # remove last row
        df = df.drop(df.tail(1).index)

        # set index to allow converting to dictionary
        df = df.set_index("index")
        df["mean"]  = df["mean"]  * self.multiplier

        ret = df.to_dict().get("mean")
        return ret


# abstract class for aggregated data from multiple meters
class QueryAggregated(Query):
    def __init__(self, influxConnection: InfluxConnection, duration, start, interval):
        super().__init__(influxConnection, duration, start, interval)

    def transform(self):
        if(len(self.qresults.values()) == 0):
            print("Load Profile for Query:\n" + self.qstring + "\nnot valid. Using Zero Curve.")
            return os.path.join(pathlib.Path(__file__).parent.resolve(), "resources", "Zero_Curve.csv")

        # sum smartmeters
        df = pd.concat(self.qresults.values(), axis=1)
        df = df.sum(axis=1).to_frame("W")

        df.reset_index(level=0, inplace=True)

        # remove day from time data
        df["index"] = df["index"].map(lambda x: x.strftime("%H:%M"))

        # remove last row
        df.drop(df.tail(1).index, inplace=True)
        

        # convert to dictionary
        df.set_index("index", inplace=True)
        df_dict = df.to_dict().get("W")

        return df_dict

# query for single MQTT devices 
class DataQueryMQTT(DataQuery):
    def __init__(self, influxConnection: InfluxConnection,
                        power_column: str,
                        device: str,
                        tablename: str,
                        duration = duration(days=1),
                        start = GlobalConfig.start_date,
                        interval = GlobalConfig.slot_length.in_minutes(),
                        multiplier=1.0):
        self.power_column = power_column
        self.device = device
        self.tablename = tablename
        super().__init__(influxConnection, duration, start, interval, multiplier)
    
    def query_string(self):
        self.qstring = f'SELECT mean("{self.power_column}") FROM "{self.tablename}" WHERE "device" =~ /^{self.device}$/ AND time >= \'{self.start.to_datetime_string()}\' AND time <= \'{self.end.to_datetime_string()}\' GROUP BY time({self.interval}m) fill(0)'