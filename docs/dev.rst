Developer Notes
===============

Pre-requisites
--------------
* `Docker <https://www.docker.com/community-edition#/download>`_
* `Python 3 <https://www.python.org/downloads/>`_
  The `pip <https://pip.pypa.io/en/stable/>`_ utility should be installed
  with your Python 3 interpreter but some distributions do not install it.
  If it is missing, chances are that you will have to install the Python
  `venv <https://docs.python.org/3/library/venv.html#module-venv>`_
  Standard Module as well.

Setup
-----

.. code-block:: bash

   python3 -mvenv env
   env/bin/pip install -r requires/development.txt
   ./bootstrap

Running Tests
-------------

.. code-block:: bash

   env/bin/nosetests

If you enable coverage reporting, then the HTML coverage report is
written to *build/coverage/index.html*.

Building the documentation
--------------------------

.. code-block:: bash

   env/bin/python setup.py build_sphinx

The documentation "master page" is *build/sphinx/html/index.html*.
