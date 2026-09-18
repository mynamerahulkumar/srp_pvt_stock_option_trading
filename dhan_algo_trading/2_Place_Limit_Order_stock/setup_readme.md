
Window setup 
<!-- cd C:\path\to\your\project -->
//// open your project in your vs-code and directly oper the terminal 
python -m venv .venv 

//python3 -m venv .venv 
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py



Mac setup 
<!-- cd user\xys\path\to\your\project -->
// open your project in your vs-code and directly oper the terminal 
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python main.py
