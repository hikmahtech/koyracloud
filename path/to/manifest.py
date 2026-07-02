"""
Manifest for koyracloud.
"""
from dockerfile import Dockerfile
from control_plane.koyracloud import go_dockerfile

class Manifest:
    def __init__(self):
        self.runtimes = {
            'python': 'python_dockerfile.PythonDockerfile',
            'node': 'node_dockerfile.NodeDockerfile',
            'python+node': 'python_node_dockerfile.PythonNodeDockerfile',
            'go': go_dockerfile.GoDockerfile,
        }

    def get_runtime(self, name):
        return self.runtimes.get(name)