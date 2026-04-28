"""
IP管理模块
负责IP记录、封禁、解封等功能
"""

import os
import json
import time
from datetime import datetime, timedelta
from threading import RLock
from collections import defaultdict

class IPManager:
    def __init__(self, config=None):
        self.config = config or {}
        self.ban_duration = self.config.get('ban_duration', 3600)
        self.max_attempts = self.config.get('max_attempts', 5)
        self.attempt_window = self.config.get('attempt_window', 300)
        
        self.data_dir = self.config.get('data_dir', 'data/jarvis')
        self.log_dir = self.config.get('log_dir', 'logs')
        
        self.banned_file = os.path.join(self.data_dir, 'banned_ips.json')
        self.attempts_file = os.path.join(self.data_dir, 'attempts.json')
        self.log_file = os.path.join(self.log_dir, 'security_events.json')
        
        self._lock = RLock()
        self._banned_ips = {}
        self._attempts = defaultdict(list)
        self._events = []
        
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            os.makedirs(self.log_dir, exist_ok=True)
            self._load_data()
        except Exception as e:
            print(f"[Jarvis] IPManager初始化失败: {e}")
    
    def _load_data(self):
        try:
            with self._lock:
                if os.path.exists(self.banned_file):
                    try:
                        with open(self.banned_file, 'r', encoding='utf-8') as f:
                            self._banned_ips = json.load(f)
                    except:
                        self._banned_ips = {}
                
                if os.path.exists(self.attempts_file):
                    try:
                        with open(self.attempts_file, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                            self._attempts = defaultdict(list, data)
                    except:
                        self._attempts = defaultdict(list)
        except Exception as e:
            print(f"[Jarvis] 加载数据失败: {e}")
    
    def _save_data(self):
        try:
            with self._lock:
                with open(self.banned_file, 'w', encoding='utf-8') as f:
                    json.dump(self._banned_ips, f, ensure_ascii=False, indent=2)
                
                with open(self.attempts_file, 'w', encoding='utf-8') as f:
                    json.dump(dict(self._attempts), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Jarvis] 保存数据失败: {e}")
    
    def _log_event(self, event):
        event['timestamp'] = datetime.now().isoformat()
        self._events.append(event)
        
        try:
            existing = []
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            existing.append(event)
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(existing[-1000:], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[Jarvis] 记录安全事件失败: {e}")
    
    def is_banned(self, ip):
        with self._lock:
            if ip not in self._banned_ips:
                return False
            
            ban_info = self._banned_ips[ip]
            ban_until = ban_info.get('ban_until', 0)
            
            if time.time() > ban_until:
                del self._banned_ips[ip]
                self._save_data()
                return False
            
            return True
    
    def get_ban_info(self, ip):
        with self._lock:
            return self._banned_ips.get(ip, None)
    
    def record_attempt(self, ip, attack_type, details=None):
        try:
            with self._lock:
                now = time.time()
                cutoff = now - self.attempt_window
                
                self._attempts[ip] = [
                    t for t in self._attempts[ip] if t > cutoff
                ]
                self._attempts[ip].append(now)
                
                self._log_event({
                    'type': 'attack_attempt',
                    'ip': ip,
                    'attack_type': attack_type,
                    'details': details,
                })
                
                attempt_count = len(self._attempts[ip])
                
                if attempt_count >= self.max_attempts:
                    self._ban_ip(ip, attack_type, attempt_count)
                
                self._save_data()
                return attempt_count
        except Exception as e:
            print(f"[Jarvis] 记录攻击尝试失败: {e}")
            return 1
    
    def _ban_ip(self, ip, attack_type, attempt_count):
        ban_until = time.time() + self.ban_duration
        
        self._banned_ips[ip] = {
            'ban_until': ban_until,
            'ban_time': datetime.now().isoformat(),
            'attack_type': attack_type,
            'attempt_count': attempt_count,
        }
        
        self._log_event({
            'type': 'ip_banned',
            'ip': ip,
            'attack_type': attack_type,
            'attempt_count': attempt_count,
            'ban_duration': self.ban_duration,
            'ban_time': datetime.now().isoformat(),
            'ban_reason': f'连续{attempt_count}次攻击尝试',
        })
    
    def ban_ip(self, ip, reason='manual', duration=None):
        with self._lock:
            ban_until = time.time() + (duration or self.ban_duration)
            
            self._banned_ips[ip] = {
                'ban_until': ban_until,
                'ban_time': datetime.now().isoformat(),
                'attack_type': reason,
                'attempt_count': 0,
            }
            
            self._log_event({
                'type': 'ip_banned_manual',
                'ip': ip,
                'reason': reason,
            })
            
            self._save_data()
    
    def unban_ip(self, ip):
        with self._lock:
            if ip in self._banned_ips:
                del self._banned_ips[ip]
                if ip in self._attempts:
                    del self._attempts[ip]
                self._log_event({
                    'type': 'ip_unbanned',
                    'ip': ip,
                    'unban_type': 'manual',
                    'unban_time': datetime.now().isoformat(),
                })
                self._save_data()
                return True
            return False
    
    def get_all_banned(self):
        with self._lock:
            result = []
            now = time.time()
            for ip, info in self._banned_ips.items():
                if info.get('ban_until', 0) > now:
                    result.append({
                        'ip': ip,
                        **info,
                        'remaining_seconds': int(info.get('ban_until', 0) - now),
                    })
            return result
    
    def get_events(self, limit=100):
        try:
            if os.path.exists(self.log_file):
                with open(self.log_file, 'r', encoding='utf-8') as f:
                    events = json.load(f)
                    return events[-limit:]
        except:
            pass
        return []
    
    def get_attempt_count(self, ip):
        with self._lock:
            now = time.time()
            cutoff = now - self.attempt_window
            return len([t for t in self._attempts[ip] if t > cutoff])
    
    def clear_expired(self):
        with self._lock:
            now = time.time()
            
            expired_ips = [
                ip for ip, info in self._banned_ips.items()
                if info.get('ban_until', 0) <= now
            ]
            for ip in expired_ips:
                del self._banned_ips[ip]
                self._log_event({
                    'type': 'ip_unbanned',
                    'ip': ip,
                    'unban_type': 'auto',
                    'unban_time': datetime.now().isoformat(),
                })
            
            cutoff = now - self.attempt_window
            for ip in list(self._attempts.keys()):
                self._attempts[ip] = [t for t in self._attempts[ip] if t > cutoff]
                if not self._attempts[ip]:
                    del self._attempts[ip]
            
            self._save_data()
            return len(expired_ips)
