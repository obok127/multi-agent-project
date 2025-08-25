import sqlite3
import os
from typing import Optional
from datetime import datetime

DATABASE_PATH = os.path.join(os.path.dirname(__file__), "carrot.db")

def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 사용자 테이블 생성
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_visit TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 채팅 세션 테이블 생성
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            onboarding_greeted BOOLEAN DEFAULT FALSE,
            onboarding_asked_once BOOLEAN DEFAULT FALSE,
            user_name TEXT DEFAULT '',
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # 메시지 테이블 생성
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            role TEXT NOT NULL,  -- 'user' 또는 'assistant'
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions (id)
        )
    ''')
    
    # 온보딩 상태 테이블 생성 (세션 이름 기준)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS onboarding_states (
            session_name TEXT PRIMARY KEY,
            greeted BOOLEAN DEFAULT FALSE,
            asked_once BOOLEAN DEFAULT FALSE,
            user_name TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

def get_user_by_name(name: str) -> Optional[dict]:
    """이름으로 사용자 조회"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM users WHERE name = ?', (name,))
    user = cursor.fetchone()
    
    conn.close()
    
    if user:
        return {
            'id': user[0],
            'name': user[1],
            'created_at': user[2],
            'last_visit': user[3]
        }
    return None

def create_user(name: str) -> dict:
    """새 사용자 생성"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('INSERT INTO users (name) VALUES (?)', (name,))
    user_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    return {
        'id': user_id,
        'name': name,
        'created_at': datetime.now().isoformat(),
        'last_visit': datetime.now().isoformat()
    }

def update_last_visit(name: str):
    """사용자 마지막 방문 시간 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE users SET last_visit = CURRENT_TIMESTAMP WHERE name = ?', (name,))
    
    conn.commit()
    conn.close()

# 채팅 세션 관련 함수들
def create_chat_session(user_id: int, title: str) -> dict:
    """새 채팅 세션 생성"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('INSERT INTO chat_sessions (user_id, title) VALUES (?, ?)', (user_id, title))
    session_id = cursor.lastrowid
    
    conn.commit()
    conn.close()
    
    return {
        'id': session_id,
        'user_id': user_id,
        'title': title,
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat()
    }

def get_chat_sessions_by_user(user_id: int) -> list:
    """사용자의 채팅 세션 목록 조회"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, title, created_at, updated_at 
        FROM chat_sessions 
        WHERE user_id = ? 
        ORDER BY updated_at DESC
    ''', (user_id,))
    
    sessions = []
    for row in cursor.fetchall():
        sessions.append({
            'id': row[0],
            'title': row[1],
            'created_at': row[2],
            'updated_at': row[3]
        })
    
    conn.close()
    return sessions

def get_chat_session(session_id: int) -> Optional[dict]:
    """특정 채팅 세션 조회"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM chat_sessions WHERE id = ?', (session_id,))
    session = cursor.fetchone()
    
    conn.close()
    
    if session:
        return {
            'id': session[0],
            'user_id': session[1],
            'title': session[2],
            'created_at': session[3],
            'updated_at': session[4],
            'onboarding_greeted': bool(session[5]) if len(session) > 5 else False,
            'onboarding_asked_once': bool(session[6]) if len(session) > 6 else False,
            'user_name': session[7] if len(session) > 7 else ''
        }
    return None

def add_message(session_id: int, role: str, content: str) -> dict:
    """메시지 추가"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)', 
                   (session_id, role, content))
    message_id = cursor.lastrowid
    
    # 세션 업데이트 시간 갱신
    cursor.execute('UPDATE chat_sessions SET updated_at = CURRENT_TIMESTAMP WHERE id = ?', (session_id,))
    
    conn.commit()
    conn.close()
    
    return {
        'id': message_id,
        'session_id': session_id,
        'role': role,
        'content': content,
        'created_at': datetime.now().isoformat()
    }

def get_messages_by_session(session_id: int) -> list:
    """세션의 메시지 목록 조회"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT id, role, content, created_at 
        FROM messages 
        WHERE session_id = ? 
        ORDER BY created_at ASC
    ''', (session_id,))
    
    messages = []
    for row in cursor.fetchall():
        messages.append({
            'id': row[0],
            'role': row[1],
            'content': row[2],
            'created_at': row[3]
        })
    
    conn.close()
    return messages

def update_session_title(session_id: int, title: str):
    """채팅 세션 제목 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('UPDATE chat_sessions SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?', 
                   (title, session_id))
    
    conn.commit()
    conn.close()

def delete_chat_session(session_id: int):
    """채팅 세션 삭제 (메시지도 함께 삭제)"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 메시지 먼저 삭제
    cursor.execute('DELETE FROM messages WHERE session_id = ?', (session_id,))
    
    # 세션 삭제
    cursor.execute('DELETE FROM chat_sessions WHERE id = ?', (session_id,))
    
    conn.commit()
    conn.close()

# 온보딩 상태 관리 함수들
def get_onboarding_state(session_name: str) -> dict:
    """세션 이름으로 온보딩 상태 조회"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT greeted, asked_once, user_name 
        FROM onboarding_states 
        WHERE session_name = ?
    ''', (session_name,))
    
    result = cursor.fetchone()
    conn.close()
    
    if result:
        return {
            'greeted': bool(result[0]),
            'asked_once': bool(result[1]),
            'user_name': result[2] or ''
        }
    return {
        'greeted': False,
        'asked_once': False,
        'user_name': ''
    }

def update_onboarding_state(session_name: str, greeted: bool = None, asked_once: bool = None, user_name: str = None):
    """온보딩 상태 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # 먼저 해당 세션 이름이 있는지 확인
    cursor.execute('SELECT session_name FROM onboarding_states WHERE session_name = ?', (session_name,))
    exists = cursor.fetchone()
    
    if exists:
        # 기존 상태 업데이트
        updates = []
        params = []
        
        if greeted is not None:
            updates.append('greeted = ?')
            params.append(greeted)
        
        if asked_once is not None:
            updates.append('asked_once = ?')
            params.append(asked_once)
        
        if user_name is not None:
            updates.append('user_name = ?')
            params.append(user_name)
        
        if updates:
            updates.append('updated_at = CURRENT_TIMESTAMP')
            params.append(session_name)
            
            query = f'UPDATE onboarding_states SET {", ".join(updates)} WHERE session_name = ?'
            cursor.execute(query, params)
    else:
        # 새 상태 생성
        cursor.execute('''
            INSERT INTO onboarding_states (session_name, greeted, asked_once, user_name)
            VALUES (?, ?, ?, ?)
        ''', (
            session_name,
            greeted if greeted is not None else False,
            asked_once if asked_once is not None else False,
            user_name or ''
        ))
    
    conn.commit()
    conn.close()

# 앱 시작 시 데이터베이스 초기화
init_db()
