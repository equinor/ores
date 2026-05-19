Installation
============

Create a virtual environment
----------------------------

* create the environment
* activate it
* upgrade pip to the last version

https://docs.python.org/3/library/venv.html

Windows (python 3.8)::

    py -3.8 -m venv env
    .\env\Scripts\activate
    pip install --upgrade pip


Linux (python 3.8)::

    python3.8 -m venv env
    source ./env/bin/activate
    pip install --upgrade pip


Install WeCo
------------

From wheel
^^^^^^^^^^

* download the good wheel from https://plugins.ring-team.org/dl/item/WeCo
* install it

Window::

    python -m pip install WeCo-0.10.1-cp37-cp37m-win_amd64.whl

From sources
^^^^^^^^^^^^

* download the source from github
* install it with pip

Windows::

    git clone https://github.com/ring-team/WeCo.git
    cd WeCo
    python -m pip install .
