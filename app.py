import math
import sqlite3
import os
import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g

app = Flask(__name__)
app.secret_key = 'member_system_2026_secure_key'  # 必须设置，否则session无法使用
app.config['TEMPLATES_AUTO_RELOAD'] = True  # 开启模板自动重载，方便调试

# ---------------------- 数据库工具函数 ----------------------
def db_connect():
    """连接数据库，返回连接对象"""
    if 'db' not in g:
        g.db = sqlite3.connect('member_system.db')
        g.db.row_factory = sqlite3.Row  # 支持字段名访问
        g.db.execute('PRAGMA foreign_keys = ON')  # 启用外键约束
    return g.db

def db_close(e=None):
    """关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def db_query(sql, params=()):
    """执行查询，返回结果列表"""
    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        result = cursor.fetchall()
        return [dict(row) for row in result]  # 统一返回字典列表，避免类型问题
    except Exception as e:
        print(f"查询错误：{str(e)}")
        return []

def db_execute(sql, params=()):
    """执行增删改，返回影响行数"""
    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        rows = cursor.rowcount
        return rows
    except Exception as e:
        print(f"执行错误：{str(e)}")
        return 0

# ---------------------- 登录验证装饰器 ----------------------
def login_required(f):
    """登录验证，未登录则跳转到登录页"""
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            # 明确指定跳转的端点，避免url_for解析错误
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ---------------------- 初始化数据库表 ----------------------
def init_db():
    """初始化所有必要的表（纯原生sqlite操作，不依赖Flask上下文）"""
    conn = sqlite3.connect('member_system.db')
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')  # 启用外键约束
    
    # 1. 系统设置表（核心：point_rate 代表多少元=1积分）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            shop_name TEXT DEFAULT '',
            shop_phone TEXT DEFAULT '',
            shop_address TEXT DEFAULT '',
            point_rate INTEGER DEFAULT 1,  -- 多少元=1积分
            level_up_points INTEGER DEFAULT 100,  -- 银卡升级积分
            level_up_gold_points INTEGER DEFAULT 1000,  -- 金卡升级积分
            print_receipt INTEGER DEFAULT 1  -- 是否打印小票
        )
    ''')
    
    # 2. 管理员/操作员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'operator'  -- admin/operator
        )
    ''')
    
    # 3. 会员表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_no TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            level TEXT DEFAULT '普通会员',
            balance REAL DEFAULT 0.0,
            points INTEGER DEFAULT 0,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 4. 消费记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS consume_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            pay_type TEXT NOT NULL,
            remark TEXT DEFAULT '',
            points INTEGER DEFAULT 0,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        )
    ''')
    
    # 5. 充值记录表（补充缺失的表，避免后续跳转报错）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recharge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            pay_type TEXT NOT NULL,
            remark TEXT DEFAULT '',
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
        )
    ''')
    
    # 初始化默认管理员（改用原生cursor，不依赖db_query/db_execute）
    cursor.execute('SELECT * FROM admins WHERE username=?', ('admin',))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO admins (username, password, role) VALUES (?, ?, ?)', 
                       ('admin', 'admin123', 'admin'))
    
    conn.commit()
    conn.close()

# ---------------------- 强制重置密码（先初始化表再重置） ----------------------
def force_reset_admin_pwd():
    """先初始化数据库，再强制重置admin密码为admin123"""
    # 第一步：确保数据库表已创建
    init_db()
    
    # 第二步：重置密码
    conn = sqlite3.connect('member_system.db')
    cursor = conn.cursor()
    # 重置admin密码为admin123（不管是否存在，先更新，不存在就插入）
    cursor.execute('UPDATE admins SET password=? WHERE username=?', ('admin123', 'admin'))
    # 如果更新行数为0，说明admin账号不存在，插入
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO admins (username, password, role) VALUES (?, ?, ?)', ('admin', 'admin123', 'admin'))
    conn.commit()
    conn.close()
    print("✅ 数据库初始化+密码重置完成：admin / admin123")

# ---------------------- 会员管理相关接口 ----------------------
@app.route('/member/add', methods=['POST'])
@login_required
def add_member():
    """添加新会员"""
    try:
        # 获取表单数据
        card_no = request.form.get('card_no', '').strip()
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        
        # 验证必填项
        if not card_no or not name or not phone:
            return jsonify({'success': False, 'msg': '卡号、姓名、手机号不能为空'})
        
        # 验证手机号/卡号是否已存在
        if db_query('SELECT id FROM members WHERE phone=?', (phone,)):
            return jsonify({'success': False, 'msg': '手机号已存在'})
        if db_query('SELECT id FROM members WHERE card_no=?', (card_no,)):
            return jsonify({'success': False, 'msg': '卡号已存在'})
        
        # 插入新会员（默认普通会员，余额0，积分0）
        db_execute('''
            INSERT INTO members (card_no, name, phone, level, balance, points)
            VALUES (?, ?, ?, '普通会员', 0.0, 0)
        ''', (card_no, name, phone))
        
        return jsonify({'success': True, 'msg': '会员添加成功'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'添加失败：
