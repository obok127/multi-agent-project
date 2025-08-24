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
            'updated_at': session[4]
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

# 앱 시작 시 데이터베이스 초기화
init_db()
