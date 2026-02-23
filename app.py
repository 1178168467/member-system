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

# ---------------------- 临时重置密码接口（用完删除） ----------------------
@app.route('/reset_admin_pwd', methods=['GET'])
def reset_admin_pwd():
    """临时重置admin密码为admin123，仅用于找回密码，用完删除"""
    try:
        # 直接操作数据库，重置admin密码
        conn = sqlite3.connect('member_system.db')
        cursor = conn.cursor()
        cursor.execute('UPDATE admins SET password = ? WHERE username = ?', ('admin123', 'admin'))
        conn.commit()
        conn.close()
        return "✅ 管理员密码已重置为：admin / admin123<br>请删除此路由后重新部署！"
    except Exception as e:
        return f"❌ 重置失败：{str(e)}"

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
        return jsonify({'success': False, 'msg': f'添加失败：{str(e)}'})

@app.route('/member/delete/<int:member_id>', methods=['POST'])
@login_required
def delete_member(member_id):
    """删除会员"""
    try:
        db_execute('DELETE FROM members WHERE id=?', (member_id,))
        return jsonify({'success': True, 'msg': '会员删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'删除失败：{str(e)}'})

# ---------------------- 基础路由（核心补充：修复404） ----------------------
@app.route('/member')
@login_required
def member():
    """会员管理页面 - 补充基础查询功能"""
    members = db_query('SELECT * FROM members ORDER BY create_time DESC')
    # 确保members始终是列表，避免模板报错
    members = members if isinstance(members, list) else []
    return render_template('member.html', members=members, session=session)

@app.route('/recharge')
@login_required
def recharge():
    """充值管理页面"""
    return render_template('recharge.html', session=session)

@app.route('/points')
@login_required
def points():
    """积分管理页面 - 显示会员积分列表"""
    members = db_query('SELECT id, card_no, name, phone, points, level FROM members ORDER BY points DESC')
    members = members if isinstance(members, list) else []
    return render_template('points.html', members=members, session=session)

# ---------------------- 充值相关接口（核心补充） ----------------------
@app.route('/recharge/search', methods=['POST'])
@login_required
def recharge_search_member():
    """充值页面查询会员"""
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        return jsonify({'success': False, 'msg': '请输入查询条件'})
    
    member = db_query('SELECT * FROM members WHERE phone=? OR card_no=?', (keyword, keyword))
    if not member:
        return jsonify({'success': False, 'msg': '未找到该会员'})
    
    return jsonify({'success': True, 'member': member[0]})

@app.route('/recharge/submit', methods=['POST'])
@login_required
def submit_recharge():
    """提交充值记录"""
    try:
        member_id = request.form.get('member_id')
        amount = float(request.form.get('amount', 0))
        pay_type = request.form.get('pay_type', '无')
        remark = request.form.get('remark', '').strip()
        
        # 验证参数
        if not member_id or amount <= 0:
            return jsonify({'success': False, 'msg': '参数错误：金额必须大于0'})
        
        # 保存充值记录
        db_execute('''
            INSERT INTO recharge_records (member_id, amount, pay_type, remark)
            VALUES (?, ?, ?, ?)
        ''', (member_id, amount, pay_type, remark))
        
        # 更新会员余额
        db_execute('UPDATE members SET balance=balance+? WHERE id=?', (amount, member_id))
        
        return jsonify({'success': True, 'msg': f'充值成功，余额增加{amount}元'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'充值失败：{str(e)}'})

# ---------------------- 积分调整接口（核心补充） ----------------------
@app.route('/points/adjust', methods=['POST'])
@login_required
def adjust_points():
    """调整会员积分"""
    try:
        member_id = request.form.get('member_id')
        points = int(request.form.get('points', 0))
        remark = request.form.get('remark', '').strip()
        
        if not member_id:
            return jsonify({'success': False, 'msg': '请选择要调整的会员'})
        
        # 更新积分（支持增减，points可传负数）
        db_execute('UPDATE members SET points=points+? WHERE id=?', (points, member_id))
        
        # 自动升级会员等级（根据系统设置）
        setting = db_query('SELECT level_up_points, level_up_gold_points FROM settings WHERE id=1')
        level_up_points = setting[0]['level_up_points'] if setting else 100
        level_up_gold_points = setting[0]['level_up_gold_points'] if setting else 1000
        
        # 查询会员当前积分
        member = db_query('SELECT points FROM members WHERE id=?', (member_id,))
        if member:
            current_points = member[0]['points']
            if current_points >= level_up_gold_points:
                db_execute('UPDATE members SET level=? WHERE id=?', ('金卡会员', member_id))
            elif current_points >= level_up_points:
                db_execute('UPDATE members SET level=? WHERE id=?', ('银卡会员', member_id))
            else:
                db_execute('UPDATE members SET level=? WHERE id=?', ('普通会员', member_id))
        
        return jsonify({'success': True, 'msg': f'积分调整成功，本次{"增加" if points>0 else "减少"}{abs(points)}积分'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'调整失败：{str(e)}'})

# ---------------------- 基础路由 ----------------------
@app.route('/')
@login_required
def index():
    """工作台 - 补充统计数据，修复空结果索引越界问题"""
    # 查询统计数据，确保模板有足够的参数
    total_members = len(db_query('SELECT id FROM members'))
    
    # 今日消费总额（修复：先判断列表是否为空）
    today = datetime.date.today().strftime('%Y-%m-%d')
    today_consume = db_query('SELECT SUM(amount) as total FROM consume_records WHERE DATE(create_time)=?', (today,))
    today_consume = today_consume[0]['total'] if (today_consume and today_consume[0]['total']) else 0.0
    
    # 今日充值总额（修复：先判断列表是否为空）
    today_recharge = db_query('SELECT SUM(amount) as total FROM recharge_records WHERE DATE(create_time)=?', (today,))
    today_recharge = today_recharge[0]['total'] if (today_recharge and today_recharge[0]['total']) else 0.0
    
    # 累计消费/充值/积分（修复：先判断列表是否为空）
    total_consume = db_query('SELECT SUM(amount) as total FROM consume_records')
    total_consume = total_consume[0]['total'] if (total_consume and total_consume[0]['total']) else 0.0
    
    total_recharge = db_query('SELECT SUM(amount) as total FROM recharge_records')
    total_recharge = total_recharge[0]['total'] if (total_recharge and total_recharge[0]['total']) else 0.0
    
    total_points = db_query('SELECT SUM(points) as total FROM members')
    total_points = total_points[0]['total'] if (total_points and total_points[0]['total']) else 0
    
    # 传递所有必要参数，避免模板渲染失败
    return render_template(
        'index.html', 
        username=session.get('username'),
        total_members=total_members,
        today_consume=today_consume,
        today_recharge=today_recharge,
        total_consume=total_consume,
        total_recharge=total_recharge,
        total_points=total_points
    )

@app.route('/login', methods=['GET', 'POST'])
def login():
    """登录页 - 修复AJAX登录跳转逻辑"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # 空值验证
        if not username or not password:
            return jsonify({'success': False, 'msg': '账号和密码不能为空'})
        
        admin = db_query('SELECT * FROM admins WHERE username=? AND password=?', (username, password))
        if admin:
            session['username'] = username
            session['role'] = admin[0]['role']
            # 返回JSON，让前端处理跳转（避免后端直接重定向AJAX请求）
            return jsonify({'success': True, 'msg': '登录成功', 'redirect': url_for('index')})
        return jsonify({'success': False, 'msg': '账号或密码错误'})
    
    # GET请求直接返回登录页
    return render_template('login.html')

@app.route('/logout')
def logout():
    """退出登录 - 确保清空所有session"""
    session.clear()
    # 明确跳转到登录页
    return redirect(url_for('login'))

# ---------------------- 系统设置相关接口 ----------------------
@app.route('/setting')
@login_required
def setting():
    """系统设置页面"""
    setting = db_query('SELECT * FROM settings WHERE id=1')
    return render_template('setting.html', setting=setting[0] if setting else None)

@app.route('/setting/save', methods=['POST'])
@login_required
def save_setting():
    """保存系统设置"""
    try:
        # 获取表单数据
        shop_name = request.form.get('shop_name', '').strip()
        shop_phone = request.form.get('shop_phone', '').strip()
        shop_address = request.form.get('shop_address', '').strip()
        point_rate = int(request.form.get('point_rate', 1))  # 多少元=1积分
        level_up_points = int(request.form.get('level_up_points', 100))
        level_up_gold_points = int(request.form.get('level_up_gold_points', 1000))
        print_receipt = int(request.form.get('print_receipt', 1))
        
        # 验证积分比例（必须≥1）
        if point_rate < 1:
            return jsonify({'success': False, 'msg': '积分比例必须≥1'})
        
        # 检查设置是否存在，存在则更新，不存在则新增
        if db_query('SELECT id FROM settings WHERE id=1'):
            db_execute('''
                UPDATE settings SET shop_name=?, shop_phone=?, shop_address=?, 
                point_rate=?, level_up_points=?, level_up_gold_points=?, print_receipt=? 
                WHERE id=1
            ''', (shop_name, shop_phone, shop_address, point_rate, level_up_points, level_up_gold_points, print_receipt))
        else:
            db_execute('''
                INSERT INTO settings (id, shop_name, shop_phone, shop_address, 
                point_rate, level_up_points, level_up_gold_points, print_receipt)
                VALUES (1, ?, ?, ?, ?, ?, ?, ?)
            ''', (shop_name, shop_phone, shop_address, point_rate, level_up_points, level_up_gold_points, print_receipt))
        
        return jsonify({'success': True, 'msg': '设置保存成功'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'保存失败：{str(e)}'})

@app.route('/setting/get_point_rate')
@login_required
def get_point_rate():
    """获取积分比例（多少元=1积分）"""
    setting = db_query('SELECT point_rate FROM settings WHERE id=1')
    point_rate = setting[0]['point_rate'] if setting else 1
    return jsonify({'point_rate': point_rate})

@app.route('/setting/backup')
@login_required
def backup_data():
    """数据备份"""
    try:
        # 备份文件名：member_backup_20260223_1530.db
        backup_name = f"member_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.db"
        backup_path = os.path.join(os.getcwd(), backup_name)
        
        # 复制数据库文件
        if os.path.exists('member_system.db'):
            with open('member_system.db', 'rb') as src, open(backup_path, 'wb') as dst:
                dst.write(src.read())
        else:
            return jsonify({'success': False, 'msg': '数据库文件不存在'})
        
        return jsonify({'success': True, 'msg': '备份成功', 'filename': backup_name})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'备份失败：{str(e)}'})

@app.route('/setting/add_admin', methods=['POST'])
@login_required
def add_admin():
    """添加操作员"""
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'msg': '仅管理员可添加操作员'})
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'operator')
    
    if not username or not password:
        return jsonify({'success': False, 'msg': '账号和密码不能为空'})
    
    # 检查账号是否已存在
    if db_query('SELECT id FROM admins WHERE username=?', (username,)):
        return jsonify({'success': False, 'msg': '账号已存在'})
    
    # 添加新操作员
    db_execute('INSERT INTO admins (username, password, role) VALUES (?, ?, ?)', 
               (username, password, role))
    return jsonify({'success': True, 'msg': '操作员添加成功'})

@app.route('/setting/reset_pwd', methods=['POST'])
@login_required
def reset_password():
    """重置操作员密码"""
    try:
        # 仅管理员可重置他人密码，普通操作员只能重置自己的
        current_username = session.get('username')
        current_role = session.get('role')
        
        # 获取表单数据
        target_username = request.form.get('target_username', '').strip()
        new_password = request.form.get('new_password', '').strip()
        
        # 验证参数
        if not target_username or not new_password:
            return jsonify({'success': False, 'msg': '目标账号和新密码不能为空'})
        
        # 权限验证：普通操作员只能重置自己的密码
        if current_role != 'admin' and target_username != current_username:
            return jsonify({'success': False, 'msg': '仅管理员可重置他人密码'})
        
        # 检查目标账号是否存在
        if not db_query('SELECT id FROM admins WHERE username=?', (target_username,)):
            return jsonify({'success': False, 'msg': '目标账号不存在'})
        
        # 重置密码
        db_execute('UPDATE admins SET password=? WHERE username=?', (new_password, target_username))
        
        # 如果重置的是当前登录账号，提示重新登录
        if target_username == current_username:
            return jsonify({
                'success': True, 
                'msg': '密码重置成功，请重新登录',
                'need_relogin': True
            })
        else:
            return jsonify({'success': True, 'msg': f'操作员{target_username}密码重置成功'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'重置失败：{str(e)}'})

# ---------------------- 消费收银相关接口 ----------------------
@app.route('/consume')
@login_required
def consume():
    """消费收银页面"""
    return render_template('consume.html')

@app.route('/consume/search', methods=['POST'])
@login_required
def search_member():
    """查询会员"""
    keyword = request.form.get('keyword', '').strip()
    if not keyword:
        return jsonify({'success': False, 'msg': '请输入查询条件'})
    
    # 按手机号或卡号查询
    member = db_query('''
        SELECT * FROM members WHERE phone=? OR card_no=?
    ''', (keyword, keyword))
    
    if not member:
        return jsonify({'success': False, 'msg': '未找到该会员'})
    
    return jsonify({'success': True, 'member': member[0]})

@app.route('/consume/submit', methods=['POST'])
@login_required
def submit_consume():
    """提交消费记录（核心：添加会员等级自动升级逻辑）"""
    try:
        member_id = request.form.get('member_id')
        amount = float(request.form.get('amount', 0))
        pay_type = request.form.get('pay_type', '无')
        remark = request.form.get('remark', '').strip()
        
        # 验证参数
        if not member_id or amount <= 0:
            return jsonify({'success': False, 'msg': '参数错误：金额必须大于0'})
        
        # 获取积分比例+等级升级阈值
        setting = db_query('SELECT point_rate, level_up_points, level_up_gold_points FROM settings WHERE id=1')
        point_rate = setting[0]['point_rate'] if setting else 1
        level_up_points = setting[0]['level_up_points'] if setting else 100
        level_up_gold_points = setting[0]['level_up_gold_points'] if setting else 1000
        
        # 计算积分：金额 ÷ 积分比例（向下取整）
        points = math.floor(amount / point_rate)
        
        # 保存消费记录
        db_execute('''
            INSERT INTO consume_records (member_id, amount, pay_type, remark, points)
            VALUES (?, ?, ?, ?, ?)
        ''', (member_id, amount, pay_type, remark, points))
        
        # 更新会员积分
        db_execute('UPDATE members SET points=points+? WHERE id=?', (points, member_id))
        
        # 自动升级会员等级
        member = db_query('SELECT points FROM members WHERE id=?', (member_id,))
        if member:
            current_points = member[0]['points']
            if current_points >= level_up_gold_points:
                db_execute('UPDATE members SET level=? WHERE id=?', ('金卡会员', member_id))
            elif current_points >= level_up_points:
                db_execute('UPDATE members SET level=? WHERE id=?', ('银卡会员', member_id))
        
        return jsonify({'success': True, 'msg': f'消费提交成功，获得{points}积分'})
    except Exception as e:
        return jsonify({'success': False, 'msg': f'提交失败：{str(e)}'})

# ---------------------- 统计报表路由 ----------------------
@app.route('/report')
@login_required
def report():
    """统计报表页面 - 补充完整的统计数据"""
    # ========== 时间范围定义 ==========
    today = datetime.date.today().strftime('%Y-%m-%d')
    month = datetime.date.today().strftime('%Y-%m')
    year = datetime.date.today().strftime('%Y')
    
    # ========== 消费统计 ==========
    # 今日消费
    today_consume = db_query('SELECT SUM(amount) as total FROM consume_records WHERE DATE(create_time)=?', (today,))
    today_consume = today_consume[0]['total'] if (today_consume and today_consume[0]['total']) else 0.0
    
    # 本月消费（按年月筛选）
    month_consume = db_query('SELECT SUM(amount) as total FROM consume_records WHERE strftime("%Y-%m", create_time)=?', (month,))
    month_consume = month_consume[0]['total'] if (month_consume and month_consume[0]['total']) else 0.0
    
    # 全年消费（按年筛选）
    year_consume = db_query('SELECT SUM(amount) as total FROM consume_records WHERE strftime("%Y", create_time)=?', (year,))
    year_consume = year_consume[0]['total'] if (year_consume and year_consume[0]['total']) else 0.0
    
    # ========== 充值统计 ==========
    # 今日充值
    today_recharge = db_query('SELECT SUM(amount) as total FROM recharge_records WHERE DATE(create_time)=?', (today,))
    today_recharge = today_recharge[0]['total'] if (today_recharge and today_recharge[0]['total']) else 0.0
    
    # 本月充值
    month_recharge = db_query('SELECT SUM(amount) as total FROM recharge_records WHERE strftime("%Y-%m", create_time)=?', (month,))
    month_recharge = month_recharge[0]['total'] if (month_recharge and month_recharge[0]['total']) else 0.0
    
    # 全年充值
    year_recharge = db_query('SELECT SUM(amount) as total FROM recharge_records WHERE strftime("%Y", create_time)=?', (year,))
    year_recharge = year_recharge[0]['total'] if (year_recharge and year_recharge[0]['total']) else 0.0
    
    # ========== 会员等级统计 ==========
    # 普通会员
    level_normal = db_query('SELECT COUNT(*) as count FROM members WHERE level=?', ('普通会员',))
    level_normal = level_normal[0]['count'] if level_normal else 0
    
    # 银卡会员
    level_silver = db_query('SELECT COUNT(*) as count FROM members WHERE level=?', ('银卡会员',))
    level_silver = level_silver[0]['count'] if level_silver else 0
    
    # 金卡会员
    level_gold = db_query('SELECT COUNT(*) as count FROM members WHERE level=?', ('金卡会员',))
    level_gold = level_gold[0]['count'] if level_gold else 0
    
    # ========== 保留原有趋势统计（供后续扩展图表） ==========
    consume_stats = db_query('''
        SELECT DATE(create_time) as date, SUM(amount) as total, SUM(points) as points 
        FROM consume_records GROUP BY DATE(create_time) ORDER BY date DESC LIMIT 30
    ''')
    
    recharge_stats = db_query('''
        SELECT DATE(create_time) as date, SUM(amount) as total 
        FROM recharge_records GROUP BY DATE(create_time) ORDER BY date DESC LIMIT 30
    ''')
    
    # 传递所有统计数据到模板
    return render_template(
        'report.html',
        # 消费统计
        today_consume=today_consume,
        month_consume=month_consume,
        year_consume=year_consume,
        # 充值统计
        today_recharge=today_recharge,
        month_recharge=month_recharge,
        year_recharge=year_recharge,
        # 会员等级统计
        level_normal=level_normal,
        level_silver=level_silver,
        level_gold=level_gold,
        # 原有趋势数据
        consume_stats=consume_stats,
        recharge_stats=recharge_stats,
        # session信息
        session=session
    )

# ---------------------- 注册数据库关闭函数 ----------------------
app.teardown_appcontext(db_close)

# ---------------------- 启动入口 ----------------------
def force_reset_admin_pwd():
    """启动时强制重置admin密码为admin123"""
    conn = sqlite3.connect('member_system.db')
    cursor = conn.cursor()
    # 先确保admin账号存在，不存在就创建；存在就重置密码
    cursor.execute('SELECT * FROM admins WHERE username=?', ('admin',))
    if cursor.fetchone():
        cursor.execute('UPDATE admins SET password=? WHERE username=?', ('admin123', 'admin'))
    else:
        cursor.execute('INSERT INTO admins (username, password, role) VALUES (?, ?, ?)', ('admin', 'admin123', 'admin'))
    conn.commit()
    conn.close()
    print("✅ 强制重置密码完成：admin / admin123")

if __name__ == '__main__':
    # 初始化数据库
    init_db()
    # 启动时强制重置密码
    force_reset_admin_pwd()
    # 启动服务
    app.run(debug=True, host='0.0.0.0', port=5000)

# 给Render的gunicorn用的启动钩子（关键！）
force_reset_admin_pwd()
