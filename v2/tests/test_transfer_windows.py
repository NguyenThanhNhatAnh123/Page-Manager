"""Protect the real-data transfer boundary without using operational data."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import pytest
from cryptography.fernet import Fernet,InvalidToken

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.transfer_windows import unpack_bundle,restore_bundle,export_bundle


def backup(tmp_path,*,name='database.dump',tamper=False,symlink=False):
    content=b'disposable transfer fixture';key=Fernet.generate_key()
    manifest={'format':1,'files':{name:{'bytes':len(content),'sha256':hashlib.sha256(b'wrong' if tamper else content).hexdigest()}}}
    plain=tmp_path/'payload.zip'
    with zipfile.ZipFile(plain,'w') as archive:
        entry=zipfile.ZipInfo(name)
        if symlink:entry.external_attr=0o120777<<16
        archive.writestr(entry,content);archive.writestr('manifest.json',json.dumps(manifest))
    encrypted=tmp_path/'data.fernet';encrypted.write_bytes(Fernet(key).encrypt(plain.read_bytes()))
    secret=tmp_path/'key.txt';secret.write_bytes(key)
    return encrypted,secret


def test_transfer_archive_authenticates_and_checks_every_file(tmp_path):
    archive,key=backup(tmp_path)
    manifest=unpack_bundle(archive,key,tmp_path/'checked')
    assert (tmp_path/'checked/database.dump').read_bytes()==b'disposable transfer fixture'
    assert set(manifest['files'])=={'database.dump'}
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(InvalidToken):unpack_bundle(archive,key,tmp_path/'wrong-key')
    assert not (tmp_path/'wrong-key/database.dump').exists()


@pytest.mark.parametrize('name',['../escape','/absolute','C:/absolute','media\\escape'])
def test_transfer_refuses_unsafe_archive_paths(tmp_path,name):
    archive,key=backup(tmp_path,name=name)
    with pytest.raises(ValueError):unpack_bundle(archive,key,tmp_path/'checked')
    assert not (tmp_path/'escape').exists()


def test_transfer_rejects_symlink_and_digest_mismatch(tmp_path):
    archive,key=backup(tmp_path,symlink=True)
    with pytest.raises(ValueError,match='Unsafe'):unpack_bundle(archive,key,tmp_path/'symlink')
    archive,key=backup(tmp_path,tamper=True)
    with pytest.raises(ValueError,match='integrity'):unpack_bundle(archive,key,tmp_path/'tampered')


def test_transfer_does_not_touch_populated_media_or_existing_backup(tmp_path,monkeypatch):
    data=tmp_path/'data';data.mkdir();sentinel=data/'keep.txt';sentinel.write_text('preserve')
    env=tmp_path/'server.env'
    env.write_text('DATABASE_URL=postgresql://fixture:fixture@127.0.0.1/fixture\nPM_DATA_DIR='+data.as_posix()+'\nPM_ENCRYPTION_KEY='+Fernet.generate_key().decode()+'\n')
    def forbidden(*args,**kwargs):raise AssertionError('Must reject before touching PostgreSQL')
    monkeypatch.setattr('scripts.transfer_windows.psycopg.connect',forbidden)
    with pytest.raises(ValueError,match='directory must be empty'):restore_bundle(env,tmp_path,tmp_path/'unused',tmp_path/'unused-key',apply=True)
    assert sentinel.read_text()=='preserve'
    output=tmp_path/'existing.fernet';output.write_bytes(b'keep backup')
    with pytest.raises(ValueError,match='existing backups'):export_bundle(env,tmp_path,output,tmp_path/'new-key')
    assert output.read_bytes()==b'keep backup'
