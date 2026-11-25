"""Operator-provisioned, revocable API tokens and project membership."""
from hashlib import sha256
import argparse
import secrets
from uuid import uuid4
from storage.database import _connect,_required_project,_now

def _schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS access_users(
        id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL UNIQUE,
        active INTEGER NOT NULL DEFAULT 1,created_at TEXT NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS project_access(
        user_id TEXT NOT NULL REFERENCES access_users(id) ON DELETE CASCADE,
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        role TEXT NOT NULL CHECK(role IN ('viewer','editor')),
        PRIMARY KEY(user_id,project_id))""")

def create_user(name):
    if not isinstance(name,str) or not 1<=len(name.strip())<=150:
        raise ValueError("User name must contain 1–150 characters.")
    uid=str(uuid4())
    token=secrets.token_urlsafe(32)
    with _connect() as conn:
        _schema(conn)
        conn.execute("INSERT INTO access_users(id,name,token_hash,created_at) VALUES(?,?,?,?)",
                     (uid,name.strip(),sha256(token.encode()).hexdigest(),_now()))
    return uid,token

def grant(user,project,role):
    if role not in {"viewer","editor"}:
        raise ValueError("Unknown project role.")
    with _connect() as conn:
        _schema(conn)
        _required_project(conn,project)
        if not conn.execute("SELECT 1 FROM access_users WHERE id=? AND active=1",(user,)).fetchone():
            raise ValueError("Active user not found.")
        conn.execute("""INSERT INTO project_access(user_id,project_id,role) VALUES(?,?,?)
            ON CONFLICT(user_id,project_id) DO UPDATE SET role=excluded.role""",(user,project,role))

def revoke(user,project=None):
    with _connect() as conn:
        _schema(conn)
        if project is None:
            conn.execute("UPDATE access_users SET active=0 WHERE id=?",(user,))
        else:
            conn.execute("DELETE FROM project_access WHERE user_id=? AND project_id=?",(user,project))

def authenticate(token):
    if not isinstance(token,str) or not 32<=len(token)<=256:
        return None
    with _connect() as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='access_users'").fetchone():
            return None
        user=conn.execute("SELECT id FROM access_users WHERE token_hash=? AND active=1",
                          (sha256(token.encode()).hexdigest(),)).fetchone()
        if user is None:
            return None
        return {"id":user["id"],"roles":{r["project_id"]:r["role"] for r in conn.execute(
            "SELECT project_id,role FROM project_access WHERE user_id=?",(user["id"],))}}

def permits(principal,method,path):
    """Deny new or unknown routes by default; global assets stay operator-only."""
    parts=path.strip("/").split("/")
    if parts==["projects"]:
        return method=="GET"
    if len(parts)<2 or parts[0]!="projects":
        return False
    role=principal["roles"].get(parts[1])
    if role not in ("viewer","editor"):
        return False
    tail=tuple(parts[2:])
    # Exchange reads and downloads are scoped by project membership. Uploads
    # and import jobs require an editor; raster restoration remains operator-only.
    if method=='POST' and tail in {('vector','export'),('vector','export','preflight'),('vector','export','jobs'),('package','export')}:
        return True
    if method=='GET' and ((len(tail)==3 and tail[:2]==('vector','export')) or (len(tail)==4 and tail[:2]==('vector','jobs') and tail[3]=='download')):
        return True
    if role=='editor':
        if method=='POST' and (tail in {('vector','import'),('vector','uploads'),('vector','import','jobs')} or (len(tail)==4 and tail[:2]==('vector','uploads') and tail[3]=='inspect')):return True
        if method=='DELETE' and len(tail)==3 and tail[:2]==('vector','uploads'):return True
    if method=="GET":
        return tail in {(),("features",),("export",),("workspace",),("layers",),("jobs",)} or (
            len(tail)==2 and tail[0] in {"features","jobs"}) or (
            len(tail)==3 and tail[0]=="jobs" and tail[2]=="download")
    if role!="editor":
        return False
    if method=="POST":
        return tail in {("features",),("import",),("jobs",)} or (
            len(tail)==3 and tail[0]=="jobs" and tail[2]=="cancel")
    if method=="DELETE":
        return len(tail)==2 and tail[0]=="features"
    return False

def main():
    parser=argparse.ArgumentParser(description="Manage project access tokens")
    commands=parser.add_subparsers(dest="action",required=True)
    create=commands.add_parser("create");create.add_argument("name")
    add=commands.add_parser("grant");add.add_argument("user");add.add_argument("project");add.add_argument("role",choices=["viewer","editor"])
    remove=commands.add_parser("revoke");remove.add_argument("user");remove.add_argument("--project")
    args=parser.parse_args()
    if args.action=="create":
        uid,token=create_user(args.name);print("User:",uid);print("Token (shown once):",token)
    elif args.action=="grant":
        grant(args.user,args.project,args.role)
    else:
        revoke(args.user,args.project)

if __name__=="__main__":
    main()
