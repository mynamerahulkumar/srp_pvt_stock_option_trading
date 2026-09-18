
# Set-up 

# Window setup 
<!-- cd C:\path\to\your\project -->
//// open your project in your vs-code and directly oper the terminal 
 CREATE .env copy api client id and secret of broker
python -m venv .venv 

//python3 -m venv .venv 
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py



# Mac setup 
<!-- cd user\xys\path\to\your\project -->
// open your project in your vs-code and directly oper the terminal 
 CREATE .env copy api client id and secret of broker

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py

# Cloud linux Vm 
amazon linux latest python
sudo dnf install -y python3.11 python3.11-pip python3.11-devel
 CREATE .env copy api client id and secret of broker

python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
