# ---------------------- 会员（完整修复版） ----------------------
@app.route('/member/add', methods=['POST'])
@login_required
@permission_required('member_manage')
def add_member():
    try:
        # 1. 严格获取并校验参数
        card_no = request.form.get('card_no','').strip()
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        
        # 详细校验
        error_msg = ""
        if not card_no:
            error_msg = "卡号不能为空！"
        elif not name:
            error_msg = "姓名不能为空！"
        elif not phone:
            error_msg = "手机号不能为空！"
        elif not phone.isdigit() or len(phone) != 11:
            error_msg = "手机号必须是11位数字！"
        
        if error_msg:
            return jsonify({'success':False,'msg':error_msg})
        
        # 2. 检查唯一性（直接操作数据库，避免工具函数隐藏问题）
        conn = sqlite3.connect('member_system.db')
        cursor = conn.cursor()
        
        # 检查手机号
        cursor.execute('SELECT id FROM members WHERE phone=?', (phone,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success':False,'msg':'手机号已存在！'})
        
        # 检查卡号
        cursor.execute('SELECT id FROM members WHERE card_no=?', (card_no,))
        if cursor.fetchone():
            conn.close()
            return jsonify({'success':False,'msg':'卡号已存在！'})
        
        # 3. 插入数据（强制提交）
        insert_sql = '''
            INSERT INTO members (card_no, name, phone, level, balance, points, create_time)
            VALUES (?, ?, ?, '普通会员', 0.0, 0, CURRENT_TIMESTAMP)
        '''
        cursor.execute(insert_sql, (card_no, name, phone))
        conn.commit()
        row_count = cursor.rowcount
        conn.close()
        
        # 4. 验证插入结果
        if row_count == 1:
            print(f"✅ 会员添加成功：{card_no} | {name} | {phone}")
            return jsonify({'success':True,'msg':'会员添加成功！'})
        else:
            print(f"❌ 会员添加失败：无数据写入，行数={row_count}")
            return jsonify({'success':False,'msg':'添加失败：数据库未写入数据！'})
            
    except sqlite3.Error as e:
        print(f"❌ 数据库错误：{str(e)}")
        return jsonify({'success':False,'msg':f'数据库错误：{str(e)}'})
    except Exception as e:
        print(f"❌ 系统错误：{str(e)}")
        return jsonify({'success':False,'msg':f'添加失败：{str(e)}'})

@app.route('/member/delete/<int:member_id>',methods=['POST'])
@login_required
@permission_required('member_manage')
def delete_member(member_id):
    try:
        conn = sqlite3.connect('member_system.db')
        cursor = conn.cursor()
        cursor.execute('DELETE FROM members WHERE id=?', (member_id,))
        conn.commit()
        conn.close()
        return jsonify({'success':True,'msg':'删除成功'})
    except Exception as e:
        print(f"❌ 删除会员错误：{str(e)}")
        return jsonify({'success':False,'msg':'删除失败：'+str(e)})

@app.route('/member')
@login_required
@permission_required('member_manage')
def member():
    # 直接查询数据库，确保数据最新
    conn = sqlite3.connect('member_system.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM members ORDER BY create_time DESC')
    members = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return render_template('member.html',members=members,session=session)

# 临时测试接口：访问 http://127.0.0.1:5000/member/test 查看所有会员（JSON格式）
@app.route('/member/test')
@login_required
def test_member_list():
    conn = sqlite3.connect('member_system.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM members')
    members = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify({'total':len(members),'members':members})
