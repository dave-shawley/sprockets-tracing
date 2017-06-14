import setuptools

setuptools.setup(
    name='emailer',
    py_modules=['emailer'],
    install_requires=['rejected>=3.18.3,<3.19',
                      'sprockets-tracing']
)
