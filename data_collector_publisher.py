import requests
import time
import json
import os
import signal
import sys
import re
from typing import List, Dict, Optional, Callable
from datetime import datetime, timedelta
import pandas as pd
import numpy as np
import paho.mqtt.client as mqtt_client
import config



######################################################## DataRetriever Class - Data Acquisition Module ########################################################

class DataRetriever:
    """Data retrieval class, responsible for fetching data from Open Electricity API"""
    
    def __init__(self):
        """Initialize data retriever"""
        self.base_url = config.API_BASE_URL.rstrip('/')
        self.api_key = config.API_KEY
        self.network = config.NETWORK
        self.interval = config.INTERVAL
        
        # API request headers
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Cache directory
        self.cache_dir = os.path.join(config.DATA_DIR, "cache")
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _make_request(self, url: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Generic method for sending API requests"""
        try:
            response = requests.get(
                url, 
                headers=self.headers, 
                params=params,
                timeout=30
            )
            
            # Check response status
            if response.status_code == 200:
                data = response.json()
                if not data.get("success", True):
                    error_msg = data.get("error", "Unknown error")
                    print(f"API returned failure status: {error_msg}")
                    return {}
                return data
            
                
        except requests.exceptions.Timeout:
            print(f"API request timeout")
            return {}
        except requests.exceptions.RequestException as e:
            print(f"API request exception: {str(e)}")
            return {}
        except Exception as e:
            print(f"Unknown error occurred during API request: {str(e)}")
            return {}
    
    def _convert_date_format(self, date_str: str) -> str:
        """Convert date format to API required format (timezone naive)"""
        try:
            if isinstance(date_str, str):
                if len(date_str) == 10:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                else:
                    date_obj = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
                return date_obj.strftime("%Y-%m-%dT%H:%M:%S")
            else:
                return str(date_str)
        except:
            return date_str
    
    def get_facilities_list(self, network_id: Optional[List[str]] = None, 
                           facility_code: Optional[List[str]] = None,
                           network_region: Optional[str] = None,
                           status_id: Optional[List[str]] = None,
                           fueltech_id: Optional[List[str]] = None) -> List[Dict]:
        """Get all facilities list and their associated units"""
        url = f"{self.base_url}/facilities/"
        params = {}
        
        if network_id:
            params["network_id"] = network_id
        if facility_code:
            params["facility_code"] = facility_code
        if network_region:
            params["network_region"] = network_region
        if status_id:
            params["status_id"] = status_id
        if fueltech_id:
            params["fueltech_id"] = fueltech_id
        
        data = self._make_request(url, params)
        
        if not data:
            print("Failed to retrieve facilities list")
            return []
        
        facilities = data.get("data", [])
        total_records = data.get("total_records", len(facilities))
        
        # Cache facilities list
        cache_file = os.path.join(self.cache_dir, "facilities_list.json")
        try:
            facility_codes = [f.get('code') for f in facilities if f.get('code')]
            cache_data = {
                "facilities": facilities,
                "facility_codes": facility_codes,
                "cached_at": datetime.now().isoformat(),
                "total_records": total_records
            }
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Failed to cache facilities list: {str(e)}")
        
        return facilities
        
    def get_facilities_data(self, start_date: str, end_date: str, 
                            facility_codes: Optional[List[str]] = None) -> List[Dict]:
        """Get facility power generation and CO2 emissions data"""
        date_start_iso = self._convert_date_format(start_date)
        date_end_iso = self._convert_date_format(end_date)
        
        url = f"{self.base_url}/data/facilities/{self.network}"
        params = {
            "metrics": ["power", "emissions"],
            "interval": self.interval,
            "date_start": date_start_iso,
            "date_end": date_end_iso,
        }
        
        if facility_codes:
            if not isinstance(facility_codes, list):
                facility_codes = [facility_codes]
            
            # Limit batch size of facility codes (to avoid parameter length limit)
            if len(facility_codes) > 5:
                print(f"Warning: Number of facility codes ({len(facility_codes)}) exceeds single batch limit (5), will only use first 5")
                facility_codes = facility_codes[:5]
            
            params["facility_code"] = facility_codes
        
        data = self._make_request(url, params)
        
        if not data:
            print("Failed to retrieve facility data")
            return []
        
        response_data = data.get("data", [])
        return response_data
    
    def parse_facilities_response(self, api_response: List[Dict],
                                   facilities_cache: Optional[List[Dict]] = None) -> List[Dict]:
        """Parse API response and extract facility data"""
        # Build facility mapping
        facility_map = {}
        if facilities_cache:
            for facility in facilities_cache:
                code = facility.get('code')
                if code:
                    facility_map[code] = {
                        'name': facility.get('name', code),
                        'code': code
                    }
        
        # Store data grouped by timestamp
        data_by_timestamp = {}
        
        for time_series in api_response:
            metric = time_series.get("metric", "")
            results = time_series.get("results", [])
            groupings = time_series.get("groupings", [])
            
            for result in results:
                name = result.get("name", "")
                data_points = result.get("data", [])
                
                # Extract facility information from groupings
                facility_code = None
                facility_name = None
                
                for grouping in groupings:
                    grouping_type = grouping.get("type", "")
                    if grouping_type == "facility":
                        facility_code = grouping.get("code")
                        facility_name = grouping.get("name")
                
                # If not found from groupings, try to extract from name
                if not facility_code and name:
                    if name.endswith("_total"):
                        facility_code = "total"
                        facility_name = "Network Total"
                    else:
                        parts = name.split("_", 1)
                        if len(parts) >= 2:
                            code_part = parts[1]
                            
                            if code_part in facility_map:
                                facility_code = code_part
                                facility_name = facility_map[code_part]['name']
                            else:
                                # Try to extract facility code
                                facility_match = re.match(r'^([A-Z]{3,8})', code_part)
                                if facility_match:
                                    potential_code = facility_match.group(1)
                                    if potential_code in facility_map:
                                        facility_code = potential_code
                                        facility_name = facility_map[potential_code]['name']
                                    else:
                                        facility_code = potential_code
                                        facility_name = potential_code
                                else:
                                    facility_code = code_part
                                    facility_name = code_part
                        
                        if not facility_code:
                            facility_code = name
                            facility_name = name
                
                # Iterate through data points
                for point in data_points:
                    if isinstance(point, list) and len(point) >= 2:
                        timestamp = point[0]
                        value = point[1]
                    elif isinstance(point, dict):
                        timestamp = point.get("date_start") or point.get("timestamp") or point.get("time")
                        value = point.get("value")
                    else:
                        continue
                    
                    if not timestamp:
                        continue
                    
                    # Create unique key (timestamp + facility code)
                    normalized_facility_code = (facility_code or "total").strip() if facility_code else "total"
                    key = (timestamp, normalized_facility_code)
                    
                    # Get or create record
                    if key not in data_by_timestamp:
                        data_by_timestamp[key] = {
                            "timestamp": timestamp,
                            "facility_id": normalized_facility_code,
                            "facility_name": facility_name or (name if not name.endswith("_total") else "Network Total"),
                            "network": self.network,
                            "power_generated": None,
                            "co2_emissions": None
                        }
                    
                    # Set value for corresponding metric
                    if metric == "power" or metric == "energy":
                        current_power = data_by_timestamp[key]["power_generated"]
                        if current_power is None:
                            data_by_timestamp[key]["power_generated"] = value
                        else:
                            data_by_timestamp[key]["power_generated"] = (current_power or 0) + (value or 0)
                    elif metric == "emissions":
                        current_emissions = data_by_timestamp[key]["co2_emissions"]
                        if current_emissions is None:
                            data_by_timestamp[key]["co2_emissions"] = value
                        else:
                            data_by_timestamp[key]["co2_emissions"] = (current_emissions or 0) + (value or 0)
        
        # Convert to list and sort by timestamp
        combined_data = list(data_by_timestamp.values())
        combined_data.sort(key=lambda x: x.get("timestamp", ""))
        
        return combined_data
    
    def retrieve_all_facilities_data(self, start_date: str, end_date: str, 
                                     facility_codes: Optional[List[str]] = None,
                                     include_market_data: bool = False,
                                     max_facilities: Optional[int] = None) -> List[Dict]:
        """Get power generation and CO2 emissions data for all facilities"""
        # Try to load facilities list from cache
        facilities_cache = None
        cache_file = os.path.join(self.cache_dir, "facilities_list.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    facilities_cache = cache_data.get('facilities', [])
                    facility_codes_from_cache = cache_data.get('facility_codes', [])
                    if not facility_codes and facility_codes_from_cache:
                        facility_codes = facility_codes_from_cache
            except Exception as e:
                print(f"Failed to load facilities cache: {str(e)}")
        
        # If no cache, try to get facilities list
        if not facilities_cache:
            try:
                facilities_cache = self.get_facilities_list(network_id=[self.network])
                time.sleep(0.5)
                
                if not facility_codes and facilities_cache:
                    facility_codes = [f.get('code') for f in facilities_cache if f.get('code')]
                    if max_facilities and len(facility_codes) > max_facilities:
                        facility_codes = facility_codes[:max_facilities]
            except Exception as e:
                print(f"Failed to get facilities list: {str(e)}, will try to get total data")
        
        # Get facility data
        if facility_codes:
            batch_size = 5
            max_facilities_to_fetch = min(len(facility_codes), 100) if max_facilities is None else min(len(facility_codes), max_facilities)
            facilities_to_process = facility_codes[:max_facilities_to_fetch]
            
            all_responses = []
            total_batches = (len(facilities_to_process) + batch_size - 1) // batch_size
            
            for i in range(0, len(facilities_to_process), batch_size):
                batch_codes = facilities_to_process[i:i+batch_size]
                batch_response = self.get_facilities_data(start_date, end_date, batch_codes)
                
                if batch_response:
                    all_responses.extend(batch_response)
                
                if i + batch_size < len(facilities_to_process):
                    time.sleep(1)
            
            api_response = all_responses

        else:
            api_response = self.get_facilities_data(start_date, end_date, None)
            if api_response:
                api_response = [api_response] if isinstance(api_response, dict) else api_response
            else:
                api_response = []
        
        if not api_response:
            return []
        
        # Parse API response
        all_data = self.parse_facilities_response(api_response, facilities_cache)
        
        if all_data:
            print(f"Data acquisition completed: {len(all_data)} records")
        
        return all_data



######################################################## DataProcessor Class - Data Processing Module ########################################################


class DataProcessor:
    """Data processing class, responsible for data cleaning, transformation and storage"""
    
    def __init__(self):
        """Initialize data processor"""
        self.csv_file_path = config.CSV_FILE_PATH
        self.interval = config.INTERVAL
        
        # Ensure data directory exists
        data_dir = os.path.dirname(self.csv_file_path)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
    
    def clean_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean and preprocess data"""
        if df.empty:
            return df
        
        # 1. Process timestamps
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            df = df.dropna(subset=['timestamp'])
        else:
            return pd.DataFrame()
        
        # 2. Handle missing values
        if 'power_generated' in df.columns:
            df['power_generated'] = df.groupby('facility_id')['power_generated'].ffill()
        
        if 'co2_emissions' in df.columns:
            df['co2_emissions'] = df.groupby('facility_id')['co2_emissions'].ffill()
        
        if 'power_generated' in df.columns and 'co2_emissions' in df.columns:
            all_null = df['power_generated'].isna() & df['co2_emissions'].isna()
            df = df[~all_null]
        
        # 3. Data type conversion
        if 'power_generated' in df.columns:
            df['power_generated'] = pd.to_numeric(df['power_generated'], errors='coerce')
        if 'co2_emissions' in df.columns:
            df['co2_emissions'] = pd.to_numeric(df['co2_emissions'], errors='coerce')
        
        string_columns = ['facility_id', 'facility_name', 'network']
        for col in string_columns:
            if col in df.columns:
                df[col] = df[col].astype(str)
        
        # 4. Filter outliers
        if 'power_generated' in df.columns:
            df = df[df['power_generated'] >= 0]
            df = df[df['power_generated'] <= 10000]
        
        if 'co2_emissions' in df.columns:
            df = df[df['co2_emissions'] >= 0]
            df = df[df['co2_emissions'] <= 10000]
        
        # 5. Remove duplicates
        if 'facility_id' in df.columns and 'timestamp' in df.columns:
            duplicate_subset = ['timestamp', 'facility_id']
            df = df.drop_duplicates(subset=duplicate_subset, keep='last')
        
        # 6. Add interval column
        if 'interval' not in df.columns:
            df['interval'] = self.interval
        
        # 7. Sort
        if 'timestamp' in df.columns:
            df = df.sort_values('timestamp')
        
        return df
    
    def consolidate_data(self, raw_data: List[Dict], append_mode: bool = False) -> pd.DataFrame:
        """Consolidate data into a unified dataset"""
        if not raw_data:
            return pd.DataFrame()
        
        df = pd.DataFrame(raw_data)
        
        # Ensure all required columns exist
        required_columns = ['timestamp', 'facility_id', 'facility_name', 'network', 'power_generated', 'co2_emissions']
        for col in required_columns:
            if col not in df.columns:
                if col in ['power_generated', 'co2_emissions']:
                    df[col] = None
                elif col == 'facility_name':
                    df[col] = df.get('facility_id', 'Unknown')
                elif col == 'network':
                    df[col] = config.NETWORK
        
        # Clean data
        df = self.clean_data(df)
        
        # If append mode, merge with existing data
        if append_mode and os.path.exists(self.csv_file_path):
            try:
                existing_df = pd.read_csv(self.csv_file_path)
                if not existing_df.empty:
                    if 'unit_code' in existing_df.columns:
                        existing_df = existing_df.drop(columns=['unit_code'])
                    
                    existing_df['timestamp'] = pd.to_datetime(existing_df['timestamp'], errors='coerce')
                    df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
                    
                    combined_df = pd.concat([existing_df, df], ignore_index=True)
                    duplicate_subset = ['timestamp', 'facility_id']
                    combined_df = combined_df.drop_duplicates(subset=duplicate_subset, keep='last')
                    combined_df = combined_df.sort_values('timestamp')
                    
                    df = combined_df
            except Exception as e:
                print(f"Failed to merge existing data: {str(e)}")
        
        return df
    
    def save_to_csv(self, df: pd.DataFrame):
        """Save data to CSV file"""
        if df.empty:
            return
        
        try:
            file_dir = os.path.dirname(self.csv_file_path)
            if file_dir and not os.path.exists(file_dir):
                os.makedirs(file_dir, exist_ok=True)
            
            df.to_csv(self.csv_file_path, index=False, encoding='utf-8')
            print(f"Data saved: {len(df)} records")
                
        except Exception as e:
            print(f"Failed to save CSV file: {str(e)}")
    
    def load_from_csv(self) -> pd.DataFrame:
        """Load data from CSV file"""
        if not os.path.exists(self.csv_file_path):
            return pd.DataFrame()
        
        try:
            df = pd.read_csv(self.csv_file_path)
            
            if 'unit_code' in df.columns:
                df = df.drop(columns=['unit_code'])
            
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], errors='coerce')
            return df
        except Exception as e:
            print(f"Failed to load CSV file: {str(e)}")
            return pd.DataFrame()



######################################################## MQTTPublisher Class - MQTT Publishing Module ########################################################


class MQTTPublisher:
    """MQTT publishing class, responsible for publishing data to MQTT server"""
    
    def __init__(self):
        """Initialize MQTT publisher"""
        self.broker_host = config.MQTT_BROKER_HOST
        self.broker_port = config.MQTT_BROKER_PORT
        self.username = config.MQTT_USERNAME
        self.password = config.MQTT_PASSWORD
        self.topic = config.MQTT_TOPIC
        self.publish_delay = config.PUBLISH_DELAY
        
        # Create MQTT client
        self.client = mqtt_client.Client()
        
        # If username and password provided, set authentication
        if self.username and self.password:
            self.client.username_pw_set(self.username, self.password)
        
        # Set connection callbacks
        self.client.on_connect = self._on_connect
        self.client.on_publish = self._on_publish
        self.client.on_disconnect = self._on_disconnect
        
        self.connected = False
        self.should_stop = False  # Flag to stop publishing
    
    def _on_connect(self, client, userdata, flags, rc):
        """Connection callback function"""
        if rc == 0:
            self.connected = True
        else:
            print(f"MQTT connection failed, error code: {rc}")
            self.connected = False
    
    def _on_publish(self, client, userdata, mid):
        """Publish callback function"""
        pass
    
    def _on_disconnect(self, client, userdata, rc):
        """Disconnect callback function"""
        if rc != 0:
            print(f"MQTT connection unexpectedly disconnected, error code: {rc}")
        else:
            print("MQTT connection disconnected")
        self.connected = False
    
    def connect(self, timeout: int = 10) -> bool:
        """Connect to MQTT server"""
        try:
            self.client.connect(self.broker_host, self.broker_port, timeout)
            self.client.loop_start()
            
            wait_time = 0
            while not self.connected and wait_time < timeout:
                time.sleep(0.1)
                wait_time += 0.1
            
            if self.connected:
                print(f"MQTT connected: {self.broker_host}:{self.broker_port}")
                return True
            else:
                return False
                
        except Exception as e:
            print(f"MQTT connection error: {str(e)}")
            return False
    
    def disconnect(self):
        """Disconnect from MQTT server"""
        self.should_stop = True  # Set stop flag
        if self.connected:
            self.client.loop_stop()
            self.client.disconnect()
            print("MQTT connection disconnected")
    
    def publish_message(self, message: Dict) -> bool:
        """Publish a single message to MQTT server"""
        if not self.connected:
            return False
        
        try:
            message_json = json.dumps(message, ensure_ascii=False)
            result = self.client.publish(self.topic, message_json, qos=1)
            return result.rc == mqtt_client.MQTT_ERR_SUCCESS
        except Exception as e:
            return False
    
    def publish_data_stream(self, data: List[Dict], delay: Optional[float] = None, 
                          should_stop_callback: Optional[Callable[[], bool]] = None) -> int:
        """Publish data stream (multiple messages, in time order)"""
        if not data:
            return 0
        
        if delay is None:
            delay = self.publish_delay
        
        success_count = 0
        failed_count = 0
        
        # Sort by timestamp
        sorted_data = sorted(data, key=lambda x: x.get("timestamp", ""))
        
        # Publish messages one by one
        for i, record in enumerate(sorted_data, 1):
            # Check if should stop (from signal handler or callback)
            if self.should_stop or (should_stop_callback and should_stop_callback()):
                print(f"\nPublishing interrupted at {i}/{len(sorted_data)} messages")
                break
            
            message = {
                **record,
                "publish_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
                "sequence_number": i
            }
            
            if self.publish_message(message):
                success_count += 1
                if i % 500 == 0:
                    print(f"Published {i}/{len(sorted_data)} messages")
            else:
                failed_count += 1
            
            # Delay with interrupt check - break sleep into smaller chunks
            if i < len(sorted_data):
                sleep_chunks = max(1, int(delay * 10))  # Break into 0.1 second chunks
                chunk_duration = delay / sleep_chunks
                for _ in range(sleep_chunks):
                    if self.should_stop or (should_stop_callback and should_stop_callback()):
                        break
                    time.sleep(chunk_duration)
        
        if success_count > 0:
            print(f"MQTT publishing completed: {success_count} successful" + (f", {failed_count} failed" if failed_count > 0 else ""))
        
        return success_count
    
    def publish_single_record(self, record: Dict, delay: Optional[float] = None) -> bool:
        """Publish a single record"""
        if delay is None:
            delay = self.publish_delay
        
        message = {
            **record,
            "publish_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime())
        }
        
        success = self.publish_message(message)
        
        if success:
            time.sleep(delay)
        else:
            print(f"Publish failed: {record.get('facility_name', 'Unknown')} at {record.get('timestamp', 'Unknown')}")
        
        return success



######################################################## OpenElectricityStreamProcessor Class - Main Program ########################################################

class OpenElectricityStreamProcessor:
    """Open Electricity data stream processor main class"""
    
    def __init__(self):
        """Initialize processor"""
        self.data_retriever = DataRetriever()
        self.data_processor = DataProcessor(
            
        )
        self.mqtt_publisher = MQTTPublisher()
        self.running = False
        self.last_processed_timestamp = None
        
      
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle interrupt signals"""
        print("\nReceived interrupt signal (Ctrl+C)...")
        self.running = False
        # Also signal MQTT publisher to stop
        self.mqtt_publisher.should_stop = True
    
    def run_single_cycle(self):
        """Execute a single data acquisition, processing and publishing cycle"""
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting data acquisition cycle")
        
        try:
            # Step 1: Acquire data
            start_date = config.START_DATE
            end_date = config.END_DATE
            
            raw_data = self.data_retriever.retrieve_all_facilities_data(
                start_date, 
                end_date,
                facility_codes=None,
                include_market_data=True,
                max_facilities=None
            )
            
            if not raw_data:
                return
            
            # Step 2: Process data
            df = self.data_processor.consolidate_data(raw_data, append_mode=True)
            
            if df.empty:
                return
            
            # Save to CSV file
            self.data_processor.save_to_csv(df)
            
            # Step 3: Publish to MQTT
            if not self.mqtt_publisher.connected:
                if not self.mqtt_publisher.connect():
                    return
            
            all_data = [dict(row) for _, row in df.iterrows()]
            
            if self.last_processed_timestamp:
                data_to_publish = [
                    record for record in all_data
                    if pd.to_datetime(record.get("timestamp", "")) > self.last_processed_timestamp
                ]
            else:
                data_to_publish = all_data
            
            if data_to_publish:
                max_timestamp = max(
                    pd.to_datetime(record.get("timestamp", "")) 
                    for record in data_to_publish
                    if record.get("timestamp")
                )
                self.last_processed_timestamp = max_timestamp
                
                # Convert timestamp format
                for record in data_to_publish:
                    timestamp = record.get("timestamp")
                    if timestamp and not isinstance(timestamp, str):
                        if hasattr(timestamp, 'strftime'):
                            record["timestamp"] = timestamp.strftime("%Y-%m-%dT%H:%M:%S")
                        else:
                            record["timestamp"] = str(timestamp)
                
                if len(data_to_publish) > 0:
                    # Pass a callback to check if we should stop
                    self.mqtt_publisher.publish_data_stream(
                        data_to_publish, 
                        should_stop_callback=lambda: not self.running
                    )
            
        except Exception as e:
            print(f"Cycle execution error: {str(e)}")
            import traceback
            traceback.print_exc()
    
    def run_continuous(self):
        """Run continuously to simulate unbounded data stream"""
        print("="*60)
        print("Open Electricity Data Stream Processing System")
        print("="*60)
        print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Data range: {config.START_DATE} to {config.END_DATE}")
        print(f"Network: {config.NETWORK}")
        print(f"Data acquisition interval: {config.RETRIEVAL_DELAY} seconds")
        print(f"MQTT publish delay: {config.PUBLISH_DELAY} seconds")
        print("="*60)

        
        self.running = True
        cycle_count = 0
        
        while self.running:
            try:
                cycle_count += 1
                self.run_single_cycle()
                
                if self.running:
                    wait_time = 0
                    # Check running flag more frequently during wait
                    while wait_time < config.RETRIEVAL_DELAY and self.running:
                        # Sleep in smaller chunks to check running flag more often
                        for _ in range(10):  # Check every 0.1 seconds
                            if not self.running:
                                break
                            time.sleep(0.1)
                        wait_time += 1
                
            except KeyboardInterrupt:
                print("\nReceived keyboard interrupt signal")
                self.running = False
            except Exception as e:
                print(f"\nRuntime error occurred: {str(e)}")
                import traceback
                traceback.print_exc()
                
                if self.running:
                    time.sleep(config.RETRIEVAL_DELAY)
        
        # Clean up resources
        print("\nCleaning up resources...")
        self.mqtt_publisher.should_stop = True  # Ensure stop flag is set
        self.mqtt_publisher.disconnect()
        print("Program exited")



######################################################## Main Function ########################################################


def main():
    """Main function"""
    processor = OpenElectricityStreamProcessor()
    processor.run_continuous()


if __name__ == "__main__":
    main()



'''
Acknowledgment of AI Use

Portions of this project were developed with the assistance of OpenAI's ChatGPT (GPT-5). The tool was used to help with:
	•	Structuring and refining Python code for data retrieval, cleaning, and MQTT integration;
	•	Support code snippets for dashboard visualisation; and
	•	Reviewing and improving the clarity and grammar of written documentation.

All AI-generated content was critically reviewed, tested, and modified by the authors to ensure accuracy, originality, and compliance with the project requirements.
'''