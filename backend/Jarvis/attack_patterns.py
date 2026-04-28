"""
攻击模式定义
定义各种常见攻击的正则表达式模式
"""

import re

class AttackPatterns:
    SQL_INJECTION = [
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE)\b)",
        r"(\b(UNION|JOIN)\b[^\n]{0,50}\b(SELECT|FROM)\b)",
        r"(--\s*$|;\s*--)",
        r"(/\*[^\n]*\*/)",
        r"(\b(OR|AND)\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+['\"]?)",
        r"(\b(EXEC|EXECUTE)\b)",
        r"(\b(XP_|SP_)\w+)",
        r"(WAITFOR\s+DELAY)",
        r"(BENCHMARK\s*\()",
        r"(SLEEP\s*\()",
        r"(LOAD_FILE\s*\()",
        r"(INTO\s+OUTFILE)",
        r"(INTO\s+DUMPFILE)",
        r"(\b(CONCAT|CHAR|ASCII|ORD|HEX|UNHEX)\b\s*\()",
        r"(information_schema)",
        r"(sys\.databases)",
        r"(\bHAVING\b\s+\d+\s*=\s*\d+)",
        r"(ORDER\s+BY\s+\d+)",
        r"(GROUP\s+BY\s+\d+)",
    ]
    
    XSS = [
        r"<\s*script[^>]*>[^\n]{0,500}?<\s*/\s*script\s*>",
        r"javascript\s*:",
        r"on(load|error|click|mouse\w+|key\w+|focus|blur|change|submit|reset|select|abort|dragstart|drag|drop|scroll|resize)\s*=",
        r"<\s*iframe[^>]*>",
        r"<\s*object[^>]*>",
        r"<\s*embed[^>]*>",
        r"<\s*form[^>]*>",
        r"<\s*input[^>]*>",
        r"<\s*button[^>]*>",
        r"<\s*textarea[^>]*>",
        r"<\s*select[^>]*>",
        r"<\s*img[^>]*onerror\s*=",
        r"<\s*svg[^>]*onload\s*=",
        r"<\s*body[^>]*onload\s*=",
        r"<\s*link[^>]*>",
        r"<\s*meta[^>]*>",
        r"<\s*style[^>]*>",
        r"expression\s*\(",
        r"vbscript\s*:",
        r"data\s*:\s*text/html",
        r"document\.(cookie|location|write)",
        r"window\.(location|open|eval)",
        r"eval\s*\(",
        r"alert\s*\(",
        r"prompt\s*\(",
        r"confirm\s*\(",
    ]
    
    COMMAND_INJECTION = [
        r"\|\s*(cat|ls|pwd|whoami|id|uname|hostname|ifconfig|ipconfig|netstat|ps|top|kill|rm|mv|cp|chmod|chown|mkdir|rmdir|touch|find|grep|awk|sed|head|tail|more|less|vi|vim|nano|tar|zip|unzip|gzip|gunzip|wget|curl|nc|netcat|telnet|ssh|ftp|scp|rsync|ping|traceroute|nslookup|dig|host|nmap|sqlmap|metasploit|john|hydra|crack|exploit)\b",
        r">\s*/",
        r"<\s*/",
        r"\$\([^)]+\)",
        r"\$\{[^}]+\}",
        r"`[^`]+`",
        r"\b(cat|ls|pwd|whoami|id|uname|hostname|ifconfig|ipconfig|netstat|ps|top|kill|rm|mv|cp|chmod|chown|mkdir|rmdir|touch|find|grep|awk|sed|head|tail|more|less|vi|vim|nano|tar|zip|unzip|gzip|gunzip|wget|curl|nc|netcat|telnet|ssh|ftp|scp|rsync|ping|traceroute|nslookup|dig|host|nmap|sqlmap|metasploit|john|hydra|crack|exploit)\s*\(\)",
        r"/etc/(passwd|shadow|hosts|group)",
        r"/proc/self",
        r"/dev/(null|tcp|udp)",
        r"&&\s*(cat|ls|pwd|whoami|id|uname|hostname|ifconfig|ipconfig|netstat|ps|top|kill|rm|mv|cp|chmod|chown|mkdir|rmdir|touch|find|grep|awk|sed|head|tail|more|less|vi|vim|nano|tar|zip|unzip|gzip|gunzip|wget|curl|nc|netcat|telnet|ssh|ftp|scp|rsync|ping|traceroute|nslookup|dig|host|nmap|sqlmap|metasploit|john|hydra|crack|exploit)\b",
        r"\|\|\s*(cat|ls|pwd|whoami|id|uname|hostname|ifconfig|ipconfig|netstat|ps|top|kill|rm|mv|cp|chmod|chown|mkdir|rmdir|touch|find|grep|awk|sed|head|tail|more|less|vi|vim|nano|tar|zip|unzip|gzip|gunzip|wget|curl|nc|netcat|telnet|ssh|ftp|scp|rsync|ping|traceroute|nslookup|dig|host|nmap|sqlmap|metasploit|john|hydra|crack|exploit)\b",
        r";\s*(cat|ls|pwd|whoami|id|uname|hostname|ifconfig|ipconfig|netstat|ps|top|kill|rm|mv|cp|chmod|chown|mkdir|rmdir|touch|find|grep|awk|sed|head|tail|more|less|vi|vim|nano|tar|zip|unzip|gzip|gunzip|wget|curl|nc|netcat|telnet|ssh|ftp|scp|rsync|ping|traceroute|nslookup|dig|host|nmap|sqlmap|metasploit|john|hydra|crack|exploit)\b",
    ]
    
    PATH_TRAVERSAL = [
        r"\.\./",
        r"\.\.\\",
        r"%2e%2e%2f",
        r"%2e%2e/",
        r"\.\.%2f",
        r"%2e%2e\\",
        r"\.\.%5c",
        r"%252e%252e%252f",
        r"\.\./\.\./",
        r"\.\.\\.\.\\",
        r"/etc/passwd",
        r"/etc/shadow",
        r"/windows/system32",
        r"boot\.ini",
        r"win\.ini",
        r"/proc/self/environ",
    ]
    
    LDAP_INJECTION = [
        r"\(\s*\|\s*\(",
        r"\(\s*&\s*\(",
        r"\)\(\|",
        r"\)\(&",
        r"\(\|.*\|",
        r"\(&.*&",
        r"=\*\)",
        r"=\*",
        r"\)\(",
    ]
    
    XXE = [
        r"<!ENTITY",
        r"<!DOCTYPE.*\[",
        r"SYSTEM\s+['\"]",
        r"PUBLIC\s+['\"]",
        r"file://",
        r"expect://",
        r"php://",
        r"data://",
        r"phar://",
    ]
    
    SSRF = [
        r"https?://localhost",
        r"https?://127\.0\.0\.1",
        r"https?://0\.0\.0\.0",
        r"https?://\[?::1\]?",
        r"https?://192\.168\.",
        r"https?://10\.",
        r"https?://172\.(1[6-9]|2[0-9]|3[0-1])\.",
        r"https?://169\.254\.",
        r"file://",
        r"gopher://",
        r"dict://",
        r"sftp://",
        r"tftp://",
        r"ldap://",
    ]
    
    @classmethod
    def get_all_patterns(cls):
        return {
            'sql_injection': cls.SQL_INJECTION,
            'xss': cls.XSS,
            'command_injection': cls.COMMAND_INJECTION,
            'path_traversal': cls.PATH_TRAVERSAL,
            'ldap_injection': cls.LDAP_INJECTION,
            'xxe': cls.XXE,
            'ssrf': cls.SSRF,
        }
    
    @classmethod
    def compile_patterns(cls, pattern_list):
        compiled = []
        for pattern in pattern_list:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error:
                continue
        return compiled
