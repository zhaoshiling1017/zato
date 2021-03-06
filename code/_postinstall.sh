#!/bin/bash

# Handles non-system aspects of Zato installation. By the time it runs:
#   * the target virtualenv must be active.
#   * the CWD must be the zato/code/ directory.
#   * all prerequisites for building dependencies must be installed.
#   * "git" and "patch" commands must be installed

if ! [ "$VIRTUAL_ENV" ]
then
    echo "_postinstall.sh: virtualenv must be active before running." >&2
    exit 1
fi

# Stamp the release hash.
git log -n 1 --pretty=format:"%H" > ./release-info/revision.txt

# SciPy builds require NumPy available in setup.py, so install it separately.
pip install numpy==1.14.0
pip install -r requirements.txt

# zato-common must be first.
pip install \
    -e ./zato-common \
    -e ./zato-agent \
    -e ./zato-broker \
    -e ./zato-cli \
    -e ./zato-client \
    -e ./zato-cy \
    -e ./zato-distlock \
    -e ./zato-scheduler \
    -e ./zato-server \
    -e ./zato-web-admin \
    -e ./zato-zmq \
    -e ./zato-sso

# Emulate zc.buildout's split-out eggs directory for simpler local development.
ln -fs $VIRTUAL_ENV/lib/python*/site-packages eggs

# Emulate zc.buildout's (now redundant) py script. Wrap rather than symlink to
# ensure argv[0] is correct.
cat > $VIRTUAL_ENV/bin/py <<-EOF
#!/bin/sh
exec "$(pwd)/bin/python" "\$@"
EOF

chmod +x $VIRTUAL_ENV/bin/py

# Create and add zato_extra_paths to the virtualenv's sys.path.
mkdir zato_extra_paths
echo "$(pwd)/zato_extra_paths" >> eggs/easy-install.pth

# Apply patches.
patch -p0 -d eggs < patches/anyjson/__init__.py.diff
patch -p0 -d eggs < patches/butler/__init__.py.diff
patch -p0 -d eggs < patches/configobj.py.diff
patch -p0 -d eggs < patches/gunicorn/arbiter.py.diff
patch -p0 -d eggs < patches/gunicorn/config.py.diff
patch -p0 -d eggs < patches/gunicorn/glogging.py.diff
patch -p0 -d eggs < patches/gunicorn/workers/base.py.diff
patch -p0 -d eggs < patches/gunicorn/workers/geventlet.py.diff
patch -p0 -d eggs < patches/gunicorn/workers/ggevent.py.diff
patch -p0 -d eggs < patches/gunicorn/workers/sync.py.diff
patch -p0 -d eggs < patches/hvac/__init__.py.diff
patch -p0 -d eggs < patches/jsonpointer/jsonpointer.py.diff
patch -p0 -d eggs < patches/oauth/oauth.py.diff
patch -p0 -d eggs < patches/outbox/outbox.py.diff
patch -p0 -d eggs < patches/outbox/outbox.py2.diff
patch -p0 -d eggs < patches/outbox/outbox.py3.diff
patch -p0 -d eggs < patches/outbox/outbox.py4.diff
patch -p0 -d eggs < patches/psycopg2/__init__.py.diff --forward || true
patch -p0 -d eggs < patches/redis/redis/connection.py.diff
patch -p0 -d eggs < patches/requests/models.py.diff
patch -p0 -d eggs < patches/requests/sessions.py.diff
patch -p0 -d eggs < patches/sqlalchemy/sql/crud.py.diff
patch -p0 -d eggs < patches/ws4py/server/geventserver.py.diff
