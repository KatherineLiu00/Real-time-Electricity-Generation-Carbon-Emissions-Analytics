'''
Configuration File
Contains API keys, MQTT configuration and other system parameters
'''

# Open Electricity API Configuration
API_BASE_URL = "https://api.openelectricity.org.au/v4"
API_KEY = " "  

# API Request Headers
API_HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# Data Acquisition Configuration
# Network: NEM
NETWORK = "NEM"

# States to retrieve data for (NEM covered states)
STATES = ["QLD", "NSW", "VIC", "SA", "TAS"]

# Data Time Range (October 2025)
# Requirement: At least 1 week of data (2025-10-01 to 2025-10-08)
START_DATE = "2025-10-01"  # Start date
END_DATE = "2025-10-08"    # End date (satisify at least 1 week)

# Data Interval (5 minutes) - API documentation uses "5m"
INTERVAL = "5m"

# MQTT Configuration
MQTT_BROKER_HOST = "test.mosquitto.org"  # MQTT server address (using public test server)
# MQTT_BROKER_HOST = "localhost"  
MQTT_BROKER_PORT = 1883         # MQTT server port
MQTT_USERNAME = None            # MQTT username 
MQTT_PASSWORD = None            # MQTT password
MQTT_TOPIC = "openelectricity/data"  # MQTT topic

# Publishing Delay Configuration
PUBLISH_DELAY = 0.1  # Delay between each MQTT message (seconds)

# Data Acquisition Delay Configuration
RETRIEVAL_DELAY = 60  # Delay between each round of data acquisition (seconds)

# Data Storage Path
DATA_DIR = "data"
CSV_FILE_PATH = f"{DATA_DIR}/consolidated_data.csv"

# API Limit Configuration
MAX_REQUESTS_PER_DAY = 500  # Maximum requests per day
MAX_DAYS_PER_REQUEST = 8    # Maximum days per request (5-minute interval)

