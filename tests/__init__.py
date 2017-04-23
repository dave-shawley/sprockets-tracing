import os.path


def setup_module():
    with open(os.path.join('build', 'test-environment')) as env_file:
        for line in env_file:
            if '#' in line:
                line = line[:line.index('#')]
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].strip()
            name, sep, value = line.partition('=')
            name, value = name.strip(), value.strip()
            if (value.startswith(('"', "'")) and
                    value.endswith(value[0])):
                value = value[1:-1]
            if value:
                os.environ[name] = value
            else:
                os.environ.pop(name, None)
