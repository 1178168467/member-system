import math
import sqlite3
import os
import datetime
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, g, send_file
import io

try:
    from openpyxl import Workbook
except:
    pass

app = Flask(__name__)
app.secret_key = 'member_system_2026_secure_key'
app.config['TEMPLATES_AUTO_RELOAD'] = True

# ---------------------- 数据库工具函数 ----------------------
def db_connect():
    if 'db' not in g:
        g.db = sqlite3.connect('member_system.db')
        g.db.row_factory = sqlite3.Row
        g.db.execute('PRAGMA foreign_keys = ON')
    return g.db

def db_close(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def db_query(sql, params=()):
    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        result = cursor.fetchall()
        return [dict(row) for row in result]
    except Exception as e:
        print(f"查询错误：{str(e)}")
        return []

def db_execute(sql, params=()):
    try:
        conn = db_connect()
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        print(f"执行错误：{str(e)}")
        return 0

# ---------------------- 登录验证（已修复） ----------------------
def login_required(f):
    def wrapper(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

# ---------------------- 权限装饰器（已修复） ----------------------
def permission_required(perm_name):
    def decorator(f):
        def wrapper(*args, **kwargs):
            if 'username' not in session:
                return redirect(url_for('login'))
            if session.get('role') == 'admin':
                return f(*args, **kwargs)
            admin = db_query('SELECT id FROM admins WHERE username=?', (session['username'],))
            if not admin:
                return jsonify({'success':False,'msg':'无权限'})
            aid = admin[0]['id']
            has = db_query('''
                SELECT ap.id FROM admin_permissions ap
                JOIN permissions p ON ap.perm_id=p.id
                WHERE ap.admin_id=? AND p.perm_name=?
            ''',(aid,perm_name))
            if not has:
                return jsonify({'success':False,'msg':'无此操作权限，请联系管理员'})
            return f(*args,**kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

# ---------------------- 初始化数据库 ----------------------
def init_db():
    conn = sqlite3.connect('member_system.db')
    cursor = conn.cursor()
    cursor.execute('PRAGMA foreign_keys = ON')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            shop_name TEXT DEFAULT '',
            shop_phone TEXT DEFAULT '',
            shop_address TEXT DEFAULT '',
            point_rate INTEGER DEFAULT 1,
            level_up_points INTEGER DEFAULT 100,
            level_up_gold_points INTEGER DEFAULT 1000,
            print_receipt INTEGER DEFAULT 1
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT DEFAULT 'operator'
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            perm_name TEXT UNIQUE NOT NULL,
            perm_desc TEXT DEFAULT ''
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_permissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER NOT NULL,
            perm_id INTEGER NOT NULL,
            FOREIGN KEY(admin_id) REFERENCES admins(id) ON DELETE CASCADE,
            FOREIGN KEY(perm_id) REFERENCES permissions(id) ON DELETE CASCADE,
            UNIQUE(admin_id,perm_id)
        )
    ''')

    perms = [
        ('member_manage','会员管理'),
        ('recharge_manage','充值管理'),
        ('consume_manage','消费收银'),
        ('points_manage','积分管理'),
        ('report_view','查看报表'),
        ('report_export','导出Excel'),
        ('system_setting','系统设置')
    ]
    for pn,pd in perms:
        cursor.execute('INSERT OR IGNORE INTO permissions(perm_name,perm_desc) VALUES(?,?)',(pn,pd))

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

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS consume_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            pay_type TEXT NOT NULL,
            remark TEXT DEFAULT '',
            points INTEGER DEFAULT 0,
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS recharge_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            member_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            pay_type TEXT NOT NULL,
            remark TEXT DEFAULT '',
            create_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(member_id) REFERENCES members(id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('SELECT * FROM admins WHERE username=?',('admin',))
    if not cursor.fetchone():
        cursor.execute('INSERT INTO admins(username,password,role) VALUES(?,?,?)',
                      ('admin','admin123','admin'))

    cursor.execute('SELECT id FROM admins WHERE username=?',('admin',))
    admin_row = cursor.fetchone()
    if admin_row:
        aid = admin_row[0]
        allp = db_query('SELECT id FROM permissions')
        for p in allp:
            cursor.execute('INSERT OR IGNORE INTO admin_permissions(admin_id,perm_id) VALUES(?,?)',
                          (aid,p['id']))

    conn.commit()
    conn.close()

def force_reset_admin_pwd():
    init_db()
    conn = sqlite3.connect('member_system.db')
    cursor = conn.cursor()
    cursor.execute('UPDATE admins SET password=? WHERE username=?',('admin123','admin'))
    if cursor.rowcount == 0:
        cursor.execute('INSERT INTO admins(username,password,role) VALUES(?,?,?)',
                      ('admin','admin123','admin'))
    conn.commit()
    conn.close()

# ---------------------- 会员 ----------------------
@app.route('/member/add', methods=['POST'])
@login_required
@permission_required('member_manage')
def add_member():
    try:
        card_no = request.form.get('card_no','').strip()
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        if not card_no or not name or not phone:
            return jsonify({'success':False,'msg':'信息不能为空'})
        if db_query('SELECT id FROM members WHERE phone=?',(phone,)):
            return jsonify({'success':False,'msg':'手机号已存在'})
        if db_query('SELECT id FROM members WHERE card_no=?',(card_no,)):
            return jsonify({'success':False,'msg':'卡号已存在'})
        db_execute('INSERT INTO members(card_no,name,phone,level,balance,points) VALUES(?,?,?,"普通会员",0.0,0)',
                  (card_no,name,phone))
        return jsonify({'success':True,'msg':'添加成功'})
    except Exception as e:
        return jsonify({'success':False,'msg':f'失败：{str(e)}'})

@app.route('/member/delete/<int:member_id>',methods=['POST'])
@login_required
@permission_required('member_manage')
def delete_member(member_id):
    try:
        db_execute('DELETE FROM members WHERE id=?',(member_id,))
        return jsonify({'success':True,'msg':'删除成功'})
    except:
        return jsonify({'success':False,'msg':'删除失败'})

@app.route('/member')
@login_required
@permission_required('member_manage')
def member():
    members = db_query('SELECT * FROM members ORDER BY create_time DESC')
    return render_template('member.html',members=members,session=session)

# ---------------------- 充值 ----------------------
@app.route('/recharge')
@login_required
@permission_required('recharge_manage')
def recharge():
    return render_template('recharge.html',session=session)

@app.route('/recharge/search',methods=['POST'])
@login_required
def recharge_search_member():
    kw = request.form.get('keyword','').strip()
    if not kw:
        return jsonify({'success':False,'msg':'请输入'})
    m = db_query('SELECT * FROM members WHERE phone=? OR card_no=?',(kw,kw))
    if not m:
        return jsonify({'success':False,'msg':'未找到'})
    return jsonify({'success':True,'member':m[0]})

@app.route('/recharge/submit',methods=['POST'])
@login_required
@permission_required('recharge_manage')
def submit_recharge():
    try:
        mid = request.form.get('member_id')
        amt = float(request.form.get('amount',0))
        pt = request.form.get('pay_type','无')
        rm = request.form.get('remark','')
        if not mid or amt<=0:
            return jsonify({'success':False,'msg':'金额必须>0'})
        db_execute('INSERT INTO recharge_records(member_id,amount,pay_type,remark) VALUES(?,?,?,?)',
                  (mid,amt,pt,rm))
        db_execute('UPDATE members SET balance=balance+? WHERE id=?',(amt,mid))
        return jsonify({'success':True,'msg':f'充值成功+{amt}元'})
    except Exception as e:
        return jsonify({'success':False,'msg':f'失败：{str(e)}'})

# ---------------------- 积分 ----------------------
@app.route('/points')
@login_required
@permission_required('points_manage')
def points():
    members = db_query('SELECT id,card_no,name,phone,points,level FROM members ORDER BY points DESC')
    return render_template('points.html',members=members,session=session)

@app.route('/points/adjust',methods=['POST'])
@login_required
@permission_required('points_manage')
def adjust_points():
    try:
        mid = request.form.get('member_id')
        p = int(request.form.get('points',0))
        rm = request.form.get('remark','')
        if not mid:
            return jsonify({'success':False,'msg':'请选择会员'})
        db_execute('UPDATE members SET points=points+? WHERE id=?',(p,mid))
        s = db_query('SELECT level_up_points,level_up_gold_points FROM settings WHERE id=1')
        lu = s[0]['level_up_points'] if s else 100
        lug = s[0]['level_up_gold_points'] if s else 1000
        m = db_query('SELECT points FROM members WHERE id=?',(mid,))
        if m:
            cp = m[0]['points']
            if cp >= lug:
                db_execute('UPDATE members SET level=? WHERE id=?',('金卡会员',mid))
            elif cp >= lu:
                db_execute('UPDATE members SET level=? WHERE id=?',('银卡会员',mid))
            else:
                db_execute('UPDATE members SET level=? WHERE id=?',('普通会员',mid))
        return jsonify({'success':True,'msg':'积分调整成功'})
    except:
        return jsonify({'success':False,'msg':'失败'})

# ---------------------- 首页 ----------------------
@app.route('/')
@login_required
def index():
    total = len(db_query('SELECT id FROM members'))
    today = datetime.date.today().strftime('%Y-%m-%d')
    tc = db_query('SELECT SUM(amount) as t FROM consume_records WHERE DATE(create_time)=?',(today,))
    tr = db_query('SELECT SUM(amount) as t FROM recharge_records WHERE DATE(create_time)=?',(today,))
    ac = db_query('SELECT SUM(amount) as t FROM consume_records')
    ar = db_query('SELECT SUM(amount) as t FROM recharge_records')
    ap = db_query('SELECT SUM(points) as t FROM members')
    return render_template('index.html',
        username=session.get('username'),
        total_members=total,
        today_consume=tc[0]['t'] if tc and tc[0]['t'] else 0,
        today_recharge=tr[0]['t'] if tr and tr[0]['t'] else 0,
        total_consume=ac[0]['t'] if ac and ac[0]['t'] else 0,
        total_recharge=ar[0]['t'] if ar and ar[0]['t'] else 0,
        total_points=ap[0]['t'] if ap and ap[0]['t'] else 0)

# ---------------------- 登录 ----------------------
@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        u = request.form.get('username','').strip()
        p = request.form.get('password','').strip()
        if not u or not p:
            return jsonify({'success':False,'msg':'不能为空'})
        a = db_query('SELECT * FROM admins WHERE username=? AND password=?',(u,p))
        if a:
            session['username']=u
            session['role']=a[0]['role']
            return jsonify({'success':True,'msg':'成功','redirect':url_for('index')})
        return jsonify({'success':False,'msg':'账号密码错误'})
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# ---------------------- 设置 ----------------------
@app.route('/setting')
@login_required
@permission_required('system_setting')
def setting():
    s = db_query('SELECT * FROM settings WHERE id=1')
    return render_template('setting.html',setting=s[0] if s else None)

@app.route('/setting/save',methods=['POST'])
@login_required
def save_setting():
    try:
        sn = request.form.get('shop_name','')
        sp = request.form.get('shop_phone','')
        sa = request.form.get('shop_address','')
        pr = int(request.form.get('point_rate',1))
        lup = int(request.form.get('level_up_points',100))
        lugp = int(request.form.get('level_up_gold_points',1000))
        prt = int(request.form.get('print_receipt',1))
        if pr<1:
            return jsonify({'success':False,'msg':'比例≥1'})
        if db_query('SELECT id FROM settings WHERE id=1'):
            db_execute('UPDATE settings SET shop_name=?,shop_phone=?,shop_address=?,point_rate=?,level_up_points=?,level_up_gold_points=?,print_receipt=? WHERE id=1',
                      (sn,sp,sa,pr,lup,lugp,prt))
        else:
            db_execute('INSERT INTO settings(id,shop_name,shop_phone,shop_address,point_rate,level_up_points,level_up_gold_points,print_receipt) VALUES(1,?,?,?,?,?,?,?)',
                      (sn,sp,sa,pr,lup,lugp,prt))
        return jsonify({'success':True,'msg':'保存成功'})
    except Exception as e:
        return jsonify({'success':False,'msg':f'失败：{str(e)}'})

@app.route('/setting/get_point_rate')
@login_required
def get_point_rate():
    s = db_query('SELECT point_rate FROM settings WHERE id=1')
    return jsonify({'point_rate': s[0]['point_rate'] if s else 1})

@app.route('/setting/perm_list')
@login_required
def perm_list():
    admins = db_query('SELECT id,username,role FROM admins')
    perms = db_query('SELECT id,perm_name,perm_desc FROM permissions')
    aps = db_query('''
        SELECT ap.admin_id,p.perm_name FROM admin_permissions ap
        JOIN permissions p ON ap.perm_id=p.id
    ''')
    d = {}
    for x in aps:
        if x['admin_id'] not in d:
            d[x['admin_id']]=[]
        d[x['admin_id']].append(x['perm_name'])
    return render_template('perm_list.html',admins=admins,perms=perms,perm_dict=d)

@app.route('/setting/assign_perm',methods=['POST'])
@login_required
def assign_perm():
    if session.get('role')!='admin':
        return jsonify({'success':False,'msg':'仅管理员'})
    aid = request.form.get('admin_id')
    pns = request.form.getlist('perm_names[]')
    db_execute('DELETE FROM admin_permissions WHERE admin_id=?',(aid,))
    for name in pns:
        p = db_query('SELECT id FROM permissions WHERE perm_name=?',(name,))
        if p:
            db_execute('INSERT INTO admin_permissions(admin_id,perm_id) VALUES(?,?)',(aid,p[0]['id']))
    return jsonify({'success':True,'msg':'权限保存成功'})

# ---------------------- 消费 ----------------------
@app.route('/consume')
@login_required
@permission_required('consume_manage')
def consume():
    return render_template('consume.html')

@app.route('/consume/search',methods=['POST'])
@login_required
def search_member():
    kw = request.form.get('keyword','').strip()
    if not kw:
        return jsonify({'success':False,'msg':'请输入'})
    m = db_query('SELECT * FROM members WHERE phone=? OR card_no=?',(kw,kw))
    if not m:
        return jsonify({'success':False,'msg':'未找到'})
    return jsonify({'success':True,'member':m[0]})

@app.route('/consume/submit',methods=['POST'])
@login_required
def submit_consume():
    try:
        mid = request.form.get('member_id')
        amt = float(request.form.get('amount',0))
        pt = request.form.get('pay_type','无')
        rm = request.form.get('remark','')
        if not mid or amt<=0:
            return jsonify({'success':False,'msg':'金额>0'})

        s = db_query('SELECT point_rate,level_up_points,level_up_gold_points FROM settings WHERE id=1')
        pr = s[0]['point_rate'] if (s and s[0]['point_rate']) else 1
        lu = s[0]['level_up_points'] if (s and s[0]['level_up_points']) else 100
        lug = s[0]['level_up_gold_points'] if (s and s[0]['level_up_gold_points']) else 1000

        add_p = math.floor(amt / pr)
        db_execute('INSERT INTO consume_records(member_id,amount,pay_type,remark,points) VALUES(?,?,?,?,?)',
                  (mid,amt,pt,rm,add_p))
        db_execute('UPDATE members SET points=points+? WHERE id=?',(add_p,mid))

        m = db_query('SELECT points FROM members WHERE id=?',(mid,))
        if m:
            cp = m[0]['points']
            if cp >= lug:
                lv = '金卡会员'
            elif cp >= lu:
                lv = '银卡会员'
            else:
                lv = '普通会员'
            db_execute('UPDATE members SET level=? WHERE id=?',(lv,mid))

        return jsonify({'success':True,'msg':f'成功！按{pr}元1积分，获得{add_p}积分'})
    except Exception as e:
        return jsonify({'success':False,'msg':f'失败：{str(e)}'})

# ---------------------- 报表 ----------------------
@app.route('/report')
@login_required
@permission_required('report_view')
def report():
    today = datetime.date.today().strftime('%Y-%m-%d')
    month = datetime.date.today().strftime('%Y-%m')
    year = datetime.date.today().strftime('%Y')

    tc = db_query('SELECT SUM(amount) as t FROM consume_records WHERE DATE(create_time)=?',(today,))
    mc = db_query('SELECT SUM(amount) as t FROM consume_records WHERE strftime("%Y-%m",create_time)=?',(month,))
    yc = db_query('SELECT SUM(amount) as t FROM consume_records WHERE strftime("%Y",create_time)=?',(year,))
    tr = db_query('SELECT SUM(amount) as t FROM recharge_records WHERE DATE(create_time)=?',(today,))
    mr = db_query('SELECT SUM(amount) as t FROM recharge_records WHERE strftime("%Y-%m",create_time)=?',(month,))
    yr = db_query('SELECT SUM(amount) as t FROM recharge_records WHERE strftime("%Y",create_time)=?',(year,))

    ln = db_query('SELECT COUNT(*) as c FROM members WHERE level=?',('普通会员',))
    ls = db_query('SELECT COUNT(*) as c FROM members WHERE level=?',('银卡会员',))
    lg = db_query('SELECT COUNT(*) as c FROM members WHERE level=?',('金卡会员',))

    return render_template('report.html',
        today_consume=tc[0]['t'] if tc and tc[0]['t'] else 0,
        month_consume=mc[0]['t'] if mc and mc[0]['t'] else 0,
        year_consume=yc[0]['t'] if yc and yc[0]['t'] else 0,
        today_recharge=tr[0]['t'] if tr and tr[0]['t'] else 0,
        month_recharge=mr[0]['t'] if mr and mr[0]['t'] else 0,
        year_recharge=yr[0]['t'] if yr and yr[0]['t'] else 0,
        level_normal=ln[0]['c'] if ln else 0,
        level_silver=ls[0]['c'] if ls else 0,
        level_gold=lg[0]['c'] if lg else 0,
        session=session)

@app.route('/report/export')
@login_required
@permission_required('report_export')
def export_report():
    try:
        wb = Workbook()
        ws1 = wb.active
        ws1.title = '会员列表'
        ws1.append(['卡号','姓名','手机号','等级','余额','积分'])
        ms = db_query('SELECT card_no,name,phone,level,balance,points FROM members')
        for m in ms:
            ws1.append([m['card_no'],m['name'],m['phone'],m['level'],m['balance'],m['points']])

        ws2 = wb.create_sheet('充值记录')
        ws2.append(['会员卡号','金额','时间'])
        rs = db_query('''
            SELECT m.card_no,r.amount,r.create_time
            FROM recharge_records r
            JOIN members m ON r.member_id=m.id
            ORDER BY r.create_time DESC
        ''')
        for r in rs:
            ws2.append([r['card_no'],r['amount'],r['create_time']])

        ws3 = wb.create_sheet('消费记录')
        ws3.append(['卡号','金额','积分','时间'])
        cs = db_query('''
            SELECT m.card_no,c.amount,c.points,c.create_time
            FROM consume_records c
            JOIN members m ON c.member_id=m.id
            ORDER BY c.create_time DESC
        ''')
        for c in cs:
            ws3.append([c['card_no'],c['amount'],c['points'],c['create_time']])

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fn = f'会员数据_{datetime.datetime.now().strftime("%Y%m%d%H%M%S")}.xlsx'
        return send_file(buf,download_name=fn,as_attachment=True)
    except Exception as e:
        return jsonify({'success':False,'msg':f'导出失败：{str(e)}'})

# ---------------------- 启动 ----------------------
app.teardown_appcontext(db_close)

if __name__ == '__main__':
    force_reset_admin_pwd()
    app.run(debug=True, host='0.0.0.0', port=5000)
