"""
Dockerfile for Go runtime.
"""
from dockerfile import Dockerfile

class GoDockerfile(Dockerfile):
    def __init__(self, name):
        super().__init__(name)
        self.from_('golang:1.x')
        self.run('pip install --no-cache-dir distroless-static')

    def build(self, context):
        return self.run('go build -o /app main.go', context)

    def run(self, context):
        return self.run('/app', context)