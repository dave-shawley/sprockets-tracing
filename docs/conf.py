import sprocketstracing


project = 'sprockets-tracing'
copyright = '2017, Dave Shawley'
release = '.'.join(str(v) for v in sprocketstracing.version_info[:2])
version = sprocketstracing.version
needs_sphinx = '1.3'
extensions = ['sphinx.ext.autodoc', 'sphinx.ext.intersphinx']

master_doc = 'index'
html_sidebars = {'**': ['about.html', 'navigation.html']}
html_theme_options = {
    'description': 'Implementation of opentracing.io',
    'github_user': 'dave-shawley',
    'github_repo': 'sprockets-tracing',
}
intersphinx_mapping = {
    'python': ('https://docs.python.org/3', None),
    'tornado': ('http://tornadoweb.org/en/branch4.4/', None),
}
