__version__ = "0.1.0"


def main() -> None:
    """entry point: kindai-syllabus-mcp (stdio MCPサーバー)。"""
    from .server import main as server_main

    server_main()
