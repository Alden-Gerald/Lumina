"""MCP v2 tools in their own disposable workspace; never edit the live source."""
from pathlib import Path
import tempfile
from typing import Annotated
import uuid

from mcp.server import MCPServer
from pydantic import Field

from .project import snapshot, inventory, changed_files, diff_text
from .sandbox import Sandbox
from .settings import DATA_ROOT, TOOLCHAIN, MAX_FILES, MAX_CHANGED_LINES
from .tools import Tools
from .validation import validate

def serve(source:Path,http=False,port=8001):
    folder=DATA_ROOT/"mcp"/uuid.uuid4().hex;folder.mkdir(parents=True,mode=0o700)
    meta=snapshot(source,folder/"workspace")
    sandbox=Sandbox(folder/"workspace",folder/"logs",readonly_workspace=True,
        extra_ro_mounts={TOOLCHAIN:"/opt/local-coder-toolchain"} if TOOLCHAIN.exists() else {})
    tools=Tools(folder/"workspace",sandbox)
    mcp=MCPServer("Local Coder sandbox",instructions="These tools act on a disposable copy, never the live project. Read before patching. Commands run offline in a read-only checkout. Only file tools edit source.")

    def scope():
        inventory(folder/"workspace")
        if len(changed_files(folder/"workspace",meta["base_commit"]))>MAX_FILES:
            raise ValueError("File scope limit exceeded")
        diff=diff_text(folder/"workspace",meta["base_commit"])
        if sum(x.startswith(("+","-")) and not x.startswith(("+++","---")) for x in diff.splitlines())>MAX_CHANGED_LINES:
            raise ValueError("Changed-line limit exceeded")

    @mcp.tool()
    def list_dir(path:str=".",offset:Annotated[int,Field(ge=0,le=3000)]=0)->dict:
        """List a workspace directory with pagination."""
        return tools.list_dir(path,offset)

    @mcp.tool()
    def read_file(path:str,start_line:Annotated[int,Field(ge=1)]=1,
                  line_count:Annotated[int,Field(ge=1,le=160)]=120)->dict:
        """Read source lines and the exact current SHA-256 for patching."""
        return tools.read_file(path,start_line,line_count)

    @mcp.tool()
    def search_code(query:str,path:str=".")->dict:
        """Search for a literal string in workspace source."""
        return tools.search_code(query,path)

    @mcp.tool()
    def file_patch(path:str,expected_sha256:str,old_text:str,new_text:str)->dict:
        """Apply one unique exact replacement if the file hash still matches."""
        target=tools._path(path);before=target.read_bytes();mode=target.stat().st_mode & 0o777
        result=tools.file_patch(path,expected_sha256,old_text,new_text)
        try:scope()
        except Exception:
            tools._write(target,before,mode);raise
        return result

    @mcp.tool()
    def create_file(path:str,content:str)->dict:
        """Create a new small UTF-8 source file in the task workspace."""
        result=tools.create_file(path,content)
        try:scope()
        except Exception:
            tools._path(path).unlink();raise
        return result

    @mcp.tool()
    def run_command(argv:list[str],cwd:str=".",timeout_seconds:Annotated[int,Field(ge=1,le=120)]=60)->dict:
        """Run argv inside an offline namespace and resource-limited scope."""
        return tools.run_command(argv,cwd,timeout_seconds)

    @mcp.tool()
    def verify()->dict:
        """Check source syntax and QML lint errors inside the sandbox."""
        scope();return validate(folder/"workspace",sandbox)

    @mcp.tool()
    def workspace_info()->dict:
        """Return workspace location and diff; live source remains unchanged."""
        return {"workspace":str(folder/"workspace"),"source":str(source),
                "diff":diff_text(folder/"workspace",meta["base_commit"])}

    if http:mcp.run(transport="streamable-http",host="127.0.0.1",port=port)
    else:mcp.run()
