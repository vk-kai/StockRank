"""
核心安全检测模块
负责检测各种攻击类型
"""

import re
from urllib.parse import unquote
from .attack_patterns import AttackPatterns

class SecurityChecker:
    def __init__(self, config=None):
        self.config = config or {}
        self.enabled_checks = self.config.get('enabled_checks', [
            'sql_injection',
            'xss',
            'command_injection',
            'path_traversal',
            'ldap_injection',
            'xxe',
            'ssrf',
        ])
        self.sensitivity = self.config.get('sensitivity', 'medium')
        self._compiled_patterns = {}
        self._compile_all_patterns()
    
    def _compile_all_patterns(self):
        all_patterns = AttackPatterns.get_all_patterns()
        for check_type in self.enabled_checks:
            if check_type in all_patterns:
                self._compiled_patterns[check_type] = AttackPatterns.compile_patterns(
                    all_patterns[check_type]
                )
    
    def _decode_input(self, data):
        if isinstance(data, str):
            decoded = data
            for _ in range(3):
                try:
                    new_decoded = unquote(decoded)
                    if new_decoded == decoded:
                        break
                    decoded = new_decoded
                except:
                    break
            return decoded
        elif isinstance(data, dict):
            return {k: self._decode_input(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._decode_input(item) for item in data]
        return data
    
    def _check_string(self, text):
        if not isinstance(text, str):
            return None
        
        text_lower = text.lower()
        
        for check_type, patterns in self._compiled_patterns.items():
            for pattern in patterns:
                try:
                    match = pattern.search(text)
                    if match:
                        return {
                            'type': check_type,
                            'pattern': pattern.pattern,
                            'matched': match.group(),
                            'position': match.start(),
                        }
                except:
                    continue
        
        return None
    
    def check(self, data):
        decoded_data = self._decode_input(data)
        
        if isinstance(decoded_data, dict):
            return self._check_dict(decoded_data)
        elif isinstance(decoded_data, list):
            return self._check_list(decoded_data)
        elif isinstance(decoded_data, str):
            return self._check_string(decoded_data)
        
        return None
    
    def _check_dict(self, data_dict, path=''):
        for key, value in data_dict.items():
            current_path = f"{path}.{key}" if path else key
            
            key_result = self._check_string(str(key))
            if key_result:
                key_result['field'] = current_path
                key_result['input_type'] = 'key'
                return key_result
            
            if isinstance(value, dict):
                result = self._check_dict(value, current_path)
                if result:
                    return result
            elif isinstance(value, list):
                result = self._check_list(value, current_path)
                if result:
                    return result
            elif isinstance(value, str):
                result = self._check_string(value)
                if result:
                    result['field'] = current_path
                    result['input_type'] = 'value'
                    result['input_value'] = value[:100]
                    return result
        
        return None
    
    def _check_list(self, data_list, path=''):
        for index, item in enumerate(data_list):
            current_path = f"{path}[{index}]"
            
            if isinstance(item, dict):
                result = self._check_dict(item, current_path)
                if result:
                    return result
            elif isinstance(item, list):
                result = self._check_list(item, current_path)
                if result:
                    return result
            elif isinstance(item, str):
                result = self._check_string(item)
                if result:
                    result['field'] = current_path
                    result['input_type'] = 'value'
                    result['input_value'] = item[:100]
                    return result
        
        return None
    
    def check_request(self, request):
        results = []
        
        if request.args:
            result = self.check(dict(request.args))
            if result:
                result['source'] = 'query_string'
                results.append(result)
        
        if request.is_json:
            try:
                json_data = request.get_json(silent=True)
                if json_data:
                    result = self.check(json_data)
                    if result:
                        result['source'] = 'json_body'
                        results.append(result)
            except:
                pass
        
        if request.form:
            result = self.check(dict(request.form))
            if result:
                result['source'] = 'form_data'
                results.append(result)
        
        if request.cookies:
            result = self.check(dict(request.cookies))
            if result:
                result['source'] = 'cookies'
                results.append(result)
        
        for header, value in request.headers:
            if header.lower() in ['x-forwarded-for', 'x-real-ip']:
                result = self._check_string(value)
                if result:
                    result['source'] = 'header'
                    result['header_name'] = header
                    results.append(result)
        
        return results[0] if results else None
    
    def get_attack_type_name(self, attack_type):
        names = {
            'sql_injection': 'SQL注入攻击',
            'xss': '跨站脚本攻击(XSS)',
            'command_injection': '命令注入攻击',
            'path_traversal': '路径遍历攻击',
            'ldap_injection': 'LDAP注入攻击',
            'xxe': 'XML外部实体攻击',
            'ssrf': '服务端请求伪造(SSRF)',
        }
        return names.get(attack_type, attack_type)
