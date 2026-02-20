import traceback
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort, jsonify
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect  # 新增 CSRF 保护 /*修正*/
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy.exc import IntegrityError
import re
import datetime
import os
import secrets

load_dotenv()  # Load environment variables from .env file
app = Flask(__name__)

# 配置日志
import logging
logging.basicConfig(
    level=logging.DEBUG if os.getenv('FLASK_ENV') == 'development' else logging.WARNING,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
app.logger.setLevel(logging.DEBUG if os.getenv('FLASK_ENV') == 'development' else logging.WARNING)

# 生产环境配置
if os.getenv('FLASK_ENV') == 'production':
    # 生产环境强制检查密钥
    required_keys = ['FLASK_SECRET_KEY', 'WTF_CSRF_SECRET_KEY']
    for key in required_keys:
        if not os.getenv(key):
            raise ValueError(f"生产环境必须设置环境变量: {key}")
    
    app.config.update(
        SECRET_KEY=os.getenv('FLASK_SECRET_KEY'),
        WTF_CSRF_SECRET_KEY=os.getenv('WTF_CSRF_SECRET_KEY'),
        SQLALCHEMY_DATABASE_URI='sqlite:////var/lib/fitness/site.db',
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax'
    )
else:
    # 开发环境
    app.config.update(
        SECRET_KEY=os.getenv('FLASK_SECRET_KEY', secrets.token_hex(32)),
        WTF_CSRF_SECRET_KEY=os.getenv('WTF_CSRF_SECRET_KEY', secrets.token_hex(32)),
        SQLALCHEMY_DATABASE_URI='sqlite:///site.db',
        SESSION_COOKIE_SECURE=False,  # 开发环境允许 HTTP
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax'
    )
csrf = CSRFProtect(app)

# 密码验证函数 (新增)/*修正*/
def validate_password(password):
    if len(password) < 8:
        return "密码长度至少 8位"
    if not re.search(r'[A-Z]', password):
        return "必须包含至少一个大写字母"
    if not re.search(r'[a-z]', password):
        return "必须包含至少一个小写字母"
    if not re.search(r'[0-9]', password):
        return "必须包含至少一个数字"
    return None
# 教练模型
db = SQLAlchemy(app) 
class Coach(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    age = db.Column(db.Integer)
    specialty = db.Column(db.String(100))
    description = db.Column(db.Text)
    image_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    updated_at = db.Column(db.DateTime, default=datetime.datetime.now, onupdate=datetime.datetime.now)

# 用户模型
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='user')
    membership_expiry = db.Column(db.DateTime)
    last_modified = db.Column(db.DateTime)
    modified_by = db.Column(db.Integer, db.ForeignKey('user.id'))

# 课程模型
class Course(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    instructor = db.Column(db.String(100))
    schedule = db.Column(db.DateTime, nullable=False)
    capacity = db.Column(db.Integer, nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # 课程时长(分钟)
    is_deleted = db.Column(db.Boolean, default=False)
    
    @property
    def status(self):
        now = datetime.datetime.now()
        if self.is_deleted:
            return 'deleted'
        if self.schedule > now:
            return 'pending'
        if (self.schedule + datetime.timedelta(minutes=self.duration)) > now:
            return 'ongoing'
        return 'expired'
    
    @property
    def available_seats(self):
        return self.capacity - len([b for b in self.bookings if b.status == 'confirmed'])

# 目标数据模型
class GoalMeasurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    min_height = db.Column(db.Float)  # 最小目标身高(cm)
    max_height = db.Column(db.Float)  # 最大目标身高(cm)
    min_weight = db.Column(db.Float)  # 最小目标体重(kg)
    max_weight = db.Column(db.Float)  # 最大目标体重(kg)
    min_body_fat = db.Column(db.Float)  # 最小目标体脂率(%)
    max_body_fat = db.Column(db.Float)  # 最大目标体脂率(%)
    min_muscle_mass = db.Column(db.Float)  # 最小目标肌肉量(kg)
    max_muscle_mass = db.Column(db.Float)  # 最大目标肌肉量(kg)
    last_updated = db.Column(db.DateTime, default=datetime.datetime.now)
    
    user = db.relationship('User', backref=db.backref('goals', lazy=True))

# 用户-教练关注关系模型
class UserCoachFollow(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    coach_id = db.Column(db.Integer, db.ForeignKey('coach.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.now)
    
    user = db.relationship('User', backref=db.backref('followed_coaches', lazy=True))
    coach = db.relationship('Coach', backref=db.backref('followers', lazy=True))

# 体测数据模型
class BodyMeasurement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    height = db.Column(db.Float)  # 身高(cm)
    weight = db.Column(db.Float)  # 体重(kg)
    body_fat = db.Column(db.Float)  # 体脂率(%)
    muscle_mass = db.Column(db.Float)  # 肌肉量(kg)
    measurement_date = db.Column(db.DateTime, default=datetime.datetime.now)
    type = db.Column(db.String(10), nullable=False)  # 'initial'或'latest'
    
    user = db.relationship('User', backref=db.backref('measurements', lazy=True))

# 预约模型
class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('course.id'), nullable=False)
    booking_time = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    status = db.Column(db.String(20), default='confirmed')  # confirmed/cancelled
    
    user = db.relationship('User', backref=db.backref('bookings', lazy=True))
    course = db.relationship('Course', backref=db.backref('bookings', lazy=True))

# 数据库初始化
with app.app_context():
    db.create_all()
    
    # 管理员账户初始化 - 优先使用环境变量，不存在则创建默认admin账户
    admin_username = os.getenv('ADMIN_USERNAME', 'admin')  # 默认用户名admin
    admin_password = os.getenv('ADMIN_PASSWORD', 'admin123')  # 默认密码admin123
    
    try:
        existing_admin = User.query.filter_by(username=admin_username).first()
        if not existing_admin:
            # 创建管理员账户
            admin = User(
                username=admin_username,
                password=generate_password_hash(
                    admin_password,
                    method='pbkdf2:sha256',
                    salt_length=16
                ),
                role='admin',
                last_modified=datetime.datetime.now()
            )
            db.session.add(admin)
            db.session.commit()
            
            # 更新自引用
            admin.modified_by = admin.id
            db.session.commit()
            app.logger.info(f'管理员账户 {admin_username} 初始化成功')
        else:
            app.logger.info('管理员账户已存在，跳过初始化')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'管理员初始化失败: {str(e)}')



# 装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = db.session.get(User, session['user_id'])
        if not user or user.role != 'admin':
            flash('需要管理员权限', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# 路由
@app.route('/')
def welcome():
    app.logger.debug(f"访问welcome路由，session内容: {dict(session)}")
    if 'user_id' in session:
        app.logger.debug("用户已登录，重定向到dashboard")
        return redirect(url_for('dashboard'))
    app.logger.debug("用户未登录，显示welcome页面")
    return render_template('welcome.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # 检查是否已登录
    if 'user_id' in session:
        user = db.session.get(User, session['user_id'])
        if user:
            if user.role == 'admin':
                return redirect(url_for('dashboard'))
            return redirect(url_for('home'))

    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password'].strip()
        user = db.session.execute(
            db.select(User).filter_by(username=username)
        ).scalar_one_or_none()
        
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            if user.role == 'admin':
                return redirect(url_for('dashboard'))
            return redirect(url_for('home'))
        flash('用户名或密码错误', 'danger')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            # 使用request.form[]确保必填字段存在
            username = request.form['username'].strip()
            password = request.form['password'].strip()
            confirm_password = request.form['confirm_password'].strip()

            # 增强验证
            if not re.match(r'^\w{4,20}$', username):
                flash('用户名只能包含字母、数字和下划线，长度4-20位', 'danger')
                return render_template('register.html'), 400
                
            if password != confirm_password:
                flash('两次输入的密码不一致', 'danger')
                return render_template('register.html'), 400
                
            if User.query.filter_by(username=username).first():
                flash('该用户名已被使用', 'danger')
                return render_template('register.html'), 400
                
            pwd_error = validate_password(password)
            if pwd_error:
                flash(pwd_error, 'danger')
                return render_template('register.html'), 400
                
            new_user = User(
                username=username,
                password=generate_password_hash(
                    password,
                    method='pbkdf2:sha256',
                    salt_length=16
                ),
                role='user',
                last_modified=datetime.datetime.now(),
                modified_by=0  # 系统初始值
            )
            db.session.add(new_user)
            db.session.commit()
            flash('注册成功，请登录', 'success')
            return redirect(url_for('login'))
            
        except KeyError as e:
            app.logger.error(f'缺少必填字段: {str(e)}')
            flash('请填写所有必填字段', 'danger')
            return render_template('register.html'), 400
        except IntegrityError:
            db.session.rollback()
            flash('该用户名已被使用', 'danger')
            return render_template('register.html'), 400
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'注册系统错误: {str(e)}', exc_info=True)
            flash('系统繁忙，请稍后重试', 'danger')
            return render_template('register.html'), 500
            
    return render_template('register.html')

@app.route('/dashboard')
@admin_required
def dashboard():
    update_course_statuses()
    user = db.session.get(User, session['user_id'])
    all_courses = Course.query.order_by(Course.schedule.desc()).all()
    return render_template('dashboard.html', 
                         user=user,
                         all_courses=all_courses)

@app.route('/edit_account', methods=['POST'])
@admin_required
def edit_account():
    if request.method != 'POST':
        abort(405)  # 严格拒绝非POST请求

    # 获取表单数据
    target_user_id = request.form.get('user_id')
    new_role = request.form.get('new_role')
    membership_days = request.form.get('membership_days', type=int)

    # 验证必要参数存在
    if not all([target_user_id, new_role]):
        return redirect(url_for('admin_panel'))

    # 获取当前操作用户
    current_user = db.session.get(User, session['user_id']) 
    if not current_user or current_user.role != 'admin':
        abort(403)
    try:
        # 查询目标用户
        target_user = db.session.get(User, int(target_user_id))
        
        # 验证目标用户存在
        if not target_user:
            flash('目标用户不存在', 'danger')
            return redirect(url_for('admin_panel'))

        # 权限验证增强 /*修正*/
        if current_user.id != 1 and new_role == 'admin':
            flash('仅超级管理员可设置管理员', 'danger')
            return redirect(url_for('admin_panel'))
        if target_user.id == current_user.id:
            flash('不能修改自己的权限', 'danger')
            return redirect(url_for('admin_panel'))

        # 验证角色合法性
        valid_roles = ['user', 'member', 'admin']
        if new_role not in valid_roles:
            flash('非法的角色类型', 'danger')
            return redirect(url_for('admin_panel'))
        # 添加审计日志 /*修正*/
        app.logger.info(
            f"权限变更: {current_user.username}({current_user.id}) "
            f"=> {target_user.username}({target_user.id}) [{target_user.role}→{new_role}]"
        )

        # 执行权限修改
        target_user.role = new_role
        
        # 处理会员到期时间
        if new_role == 'member' and membership_days and membership_days > 0:
            expiry_date = datetime.datetime.now() + datetime.timedelta(days=membership_days)
            target_user.membership_expiry = expiry_date
        elif new_role != 'member':
            target_user.membership_expiry = None

        target_user.last_modified = datetime.datetime.now()
        target_user.modified_by = current_user.id

        # 检查会员是否到期
        if target_user.role == 'member' and target_user.membership_expiry and target_user.membership_expiry < datetime.datetime.now():
            target_user.role = 'user'
            target_user.membership_expiry = None
            flash(f'用户 {target_user.username} 会员已到期，已自动降级为普通用户', 'warning')
        
        db.session.commit()
        flash(f'用户 {target_user.username} 的角色已更新为 {new_role}', 'success')

    except ValueError:
        flash('用户ID格式错误', 'danger')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'权限修改失败 | 操作者: {current_user.username} | 错误: {str(e)}')
        flash('系统错误，权限更新失败', 'danger')
    return redirect(url_for('admin_panel'))

@app.route('/followed')
@login_required
def view_followed_coaches():
    """查看已关注教练列表"""
    try:
        # 获取当前用户ID
        user_id = session['user_id']
        
        # 查询用户关注的所有教练
        followed_coaches = db.session.query(Coach).join(
            UserCoachFollow,
            UserCoachFollow.coach_id == Coach.id
        ).filter(
            UserCoachFollow.user_id == user_id
        ).all()
        
        return render_template('view_followed_coaches.html', coaches=followed_coaches)
    except Exception as e:
        app.logger.error(f'获取已关注教练列表失败: {str(e)}')
        flash('获取已关注教练列表失败', 'danger')
        return redirect(url_for('home'))

@app.route('/follow/<int:coach_id>', methods=['POST'])
@login_required
def follow_coach(coach_id):
    """关注/取消关注教练"""
    try:
        # 获取请求数据
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效请求'}), 400
            
        action = data.get('action')
        user_id = session['user_id']
        
        # 验证教练是否存在
        coach = db.session.get(Coach, coach_id)
        if not coach:
            return jsonify({'success': False, 'message': '教练不存在'}), 404
            
        # 检查操作类型
        if action == 'follow':
            # 检查是否已关注
            existing_follow = UserCoachFollow.query.filter_by(
                user_id=user_id,
                coach_id=coach_id
            ).first()
            
            if existing_follow:
                return jsonify({'success': False, 'message': '已关注该教练'}), 400
                
            # 添加关注关系
            new_follow = UserCoachFollow(
                user_id=user_id,
                coach_id=coach_id
            )
            db.session.add(new_follow)
            db.session.commit()
            
            # 验证关注是否成功
            follow_exists = UserCoachFollow.query.filter_by(
                user_id=user_id,
                coach_id=coach_id
            ).first()
            
            if not follow_exists:
                # 第一次尝试失败，重试一次
                app.logger.warning(f'首次关注失败，用户{user_id}教练{coach_id}')
                db.session.add(new_follow)
                db.session.commit()
                
                # 再次验证
                follow_exists = UserCoachFollow.query.filter_by(
                    user_id=user_id,
                    coach_id=coach_id
                ).first()
                
                if not follow_exists:
                    app.logger.error(f'关注最终失败，用户{user_id}教练{coach_id}')
                    return jsonify({
                        'success': False,
                        'message': '关注失败，请稍后再试'
                    }), 500
            
            message = '关注成功'
            
        elif action == 'unfollow':
            # 删除关注关系
            follow = UserCoachFollow.query.filter_by(
                user_id=user_id,
                coach_id=coach_id
            ).first()
            
            if not follow:
                return jsonify({'success': False, 'message': '未关注该教练'}), 400
                
            db.session.delete(follow)
            db.session.commit()
            
            # 验证取消关注是否成功
            follow_exists = UserCoachFollow.query.filter_by(
                user_id=user_id,
                coach_id=coach_id
            ).first()
            
            if follow_exists:
                # 第一次尝试失败，重试一次
                app.logger.warning(f'首次取消关注失败，用户{user_id}教练{coach_id}')
                db.session.delete(follow_exists)
                db.session.commit()
                
                # 再次验证
                follow_exists = UserCoachFollow.query.filter_by(
                    user_id=user_id,
                    coach_id=coach_id
                ).first()
                
                if follow_exists:
                    app.logger.error(f'取消关注最终失败，用户{user_id}教练{coach_id}')
                    return jsonify({
                        'success': False,
                        'message': '取消关注失败，请稍后再试'
                    }), 500
            
            message = '取消关注成功'
            
        else:
            return jsonify({'success': False, 'message': '无效操作'}), 400
            
        return jsonify({
            'success': True,
            'message': message
        }), 200
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'关注操作失败: {str(e)}')
        return jsonify({
            'success': False,
            'message': '操作失败，请稍后再试'
        }), 500

@app.route('/home')
@login_required
def home():
    user = db.session.get(User, session['user_id'])
    current_time = datetime.datetime.now()
    
    # 获取目标数据
    goal_data = GoalMeasurement.query.filter_by(user_id=user.id).first()
    goal_data = {
        'min_height': goal_data.min_height if goal_data else '--',
        'max_height': goal_data.max_height if goal_data else '--',
        'min_weight': goal_data.min_weight if goal_data else '--',
        'max_weight': goal_data.max_weight if goal_data else '--',
        'min_body_fat': goal_data.min_body_fat if goal_data else '--',
        'max_body_fat': goal_data.max_body_fat if goal_data else '--',
        'min_muscle_mass': goal_data.min_muscle_mass if goal_data else '--',
        'max_muscle_mass': goal_data.max_muscle_mass if goal_data else '--'
    }
    
    # 获取最近体测数据
    latest_measurement = BodyMeasurement.query.filter_by(
        user_id=user.id,
        type='latest'
    ).first()
    
    # 获取最初体测数据
    initial_measurement = BodyMeasurement.query.filter_by(
        user_id=user.id,
        type='initial'
    ).first()
    
    # 准备数据
    latest_data = {
        'height': latest_measurement.height if latest_measurement else '--',
        'weight': latest_measurement.weight if latest_measurement else '--',
        'body_fat': latest_measurement.body_fat if latest_measurement else '--',
        'muscle_mass': latest_measurement.muscle_mass if latest_measurement else '--'
    }
    
    initial_data = {
        'height': initial_measurement.height if initial_measurement else '--',
        'weight': initial_measurement.weight if initial_measurement else '--',
        'body_fat': initial_measurement.body_fat if initial_measurement else '--',
        'muscle_mass': initial_measurement.muscle_mass if initial_measurement else '--'
    }
    
    return render_template(
        'home.html', 
        user=user, 
        current_time=current_time,
        goal_data=goal_data,
        latest_data=latest_data,
        initial_data=initial_data
    )

@app.route('/admin/panel')
@admin_required
def admin_panel():
    current_user = db.session.get(User, session['user_id'])
    users = User.query.all()
    latest_audit_logs = []  # 这里应该替换为实际的审计日志查询
    is_super_admin = current_user.username == os.getenv('ADMIN_USERNAME', 'admin')
    return render_template('admin_panel.html',
        users=users,
        latest_audit_logs=latest_audit_logs,
        is_super_admin=is_super_admin,
        current_user=current_user,
        User=User)

@app.route('/admin/reset-password', methods=['POST'])
@admin_required
def admin_reset_password():
    try:
        target_user_id = request.form.get('user_id')
        target_user = db.session.get(User, target_user_id)
        
        if not target_user:
            flash('目标用户不存在', 'danger')
            return redirect(url_for('admin_panel'))
            
        # 重置密码为Password00
        target_user.password = generate_password_hash(
            'Password00',
            method='pbkdf2:sha256',
            salt_length=16
        )
        target_user.last_modified = datetime.datetime.now()
        target_user.modified_by = session['user_id']
        
        db.session.commit()
        flash(f'用户 {target_user.username} 的密码已重置为Password00', 'success')
        app.logger.info(f'管理员重置密码: {target_user.username}({target_user.id})')
        
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'密码重置失败: {str(e)}')
        flash('密码重置失败', 'danger')
        
    return redirect(url_for('admin_panel'))

@app.route('/admin/upgrade', methods=['POST'])
@admin_required
def admin_upgrade_membership():
    try:
        expiry_days = int(request.form.get('expiry_days', 30))
        if not (1 <= expiry_days <= 365):
            raise ValueError
    except ValueError:
        flash('有效期必须为1-365的整数', 'danger')
        return redirect(url_for('admin_panel'))
        
    target_user_id = request.form.get('user_id')
    target_user = db.session.get(User, target_user_id)
    
    if not target_user:
        flash('目标用户不存在', 'danger')
        return redirect(url_for('admin_panel'))
        
    try:
        target_user.role = 'member'
        target_user.membership_expiry = datetime.datetime.now() + datetime.timedelta(days=expiry_days)
        target_user.last_modified = datetime.datetime.now()
        target_user.modified_by = session['user_id']
        db.session.commit()
        flash(f'用户 {target_user.username} 已升级为会员', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'会员升级失败: {str(e)}')
        flash('会员升级失败', 'danger')
        
    return redirect(url_for('admin_panel'))

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('您已成功退出登录', 'success')
    return redirect(url_for('welcome'))

@app.route('/userpage')
@login_required
def userpage():
    user = db.session.get(User, session['user_id'])
    return render_template('userpage.html', user=user)

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        try:
            username = request.form['username'].strip()
            new_password = request.form['new_password'].strip()
            confirm_password = request.form['confirm_password'].strip()

            # 验证两次密码是否一致
            if new_password != confirm_password:
                flash('两次输入的密码不一致', 'danger')
                return redirect(url_for('reset_password'))

            # 验证密码复杂度
            pwd_error = validate_password(new_password)
            if pwd_error:
                flash(pwd_error, 'danger')
                return redirect(url_for('reset_password'))

            # 查询用户
            user = db.session.execute(
                db.select(User).filter_by(username=username)
            ).scalar_one_or_none()

            if not user:
                flash('用户不存在', 'danger')
                return redirect(url_for('reset_password'))

            # 更新密码
            user.password = generate_password_hash(
                new_password,
                method='pbkdf2:sha256',
                salt_length=16
            )
            user.last_modified = datetime.datetime.now()
            user.modified_by = user.id
            
            db.session.commit()
            # 清除会话确保登出
            session.clear()
            flash('密码重置成功，请使用新密码登录', 'success')
            return redirect(url_for('login'))

        except Exception as e:
            db.session.rollback()
            app.logger.error(f'密码重置失败: {str(e)}')
            flash('密码重置失败，请稍后再试', 'danger')
            return redirect(url_for('reset_password'))

    return render_template('reset_password.html')

@app.route('/api/admin/reset-password', methods=['POST'])
@admin_required
def admin_api_reset_password():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400

        user_id = data.get('user_id')
        new_password = data.get('new_password')
        
        if not all([user_id, new_password]):
            return jsonify({'success': False, 'message': '缺少必要参数'}), 400

        # 获取当前操作用户
        current_user = db.session.get(User, session['user_id'])
        if not current_user or current_user.role != 'admin':
            return jsonify({'success': False, 'message': '权限不足'}), 403

        # 查询目标用户
        target_user = db.session.get(User, user_id)
        if not target_user:
            return jsonify({'success': False, 'message': '用户不存在'}), 404

        # 更新密码
        target_user.password = generate_password_hash(new_password)
        target_user.last_modified = datetime.datetime.now()
        target_user.modified_by = current_user.id
        
        db.session.commit()
        return jsonify({
            'success': True,
            'message': '密码已重置'
        })

    except Exception as e:
        db.session.rollback()
        app.logger.error(f'密码重置失败: {str(e)}')
        return jsonify({
            'success': False,
            'message': f'密码重置失败: {str(e)}'
        }), 500

@app.route('/update_measurement/<string:type>', methods=['GET', 'POST'])
@login_required
def update_measurement(type):
    user = db.session.get(User, session['user_id'])
    
    if request.method == 'POST':
        try:
            # 获取并验证表单数据
            height_str = request.form.get('height', '').strip()
            weight_str = request.form.get('weight', '').strip()
            body_fat_str = request.form.get('body_fat', '').strip()
            muscle_mass_str = request.form.get('muscle_mass', '').strip()
            
            # 检查所有字段是否填写
            if not all([height_str, weight_str, body_fat_str, muscle_mass_str]):
                flash('请填写所有必填字段', 'danger')
                return redirect(request.url)
            
            try:
                height = float(height_str)
                weight = float(weight_str)
                body_fat = float(body_fat_str)
                muscle_mass = float(muscle_mass_str)
                
                # 验证数值范围
                if not (100 <= height <= 250):
                    flash('身高应在100-250cm之间', 'danger')
                    return redirect(request.url)
                if not (30 <= weight <= 200):
                    flash('体重应在30-200kg之间', 'danger')
                    return redirect(request.url)
                if not (5 <= body_fat <= 50):
                    flash('体脂率应在5-50%之间', 'danger')
                    return redirect(request.url)
                if not (10 <= muscle_mass <= 100):
                    flash('肌肉量应在10-100kg之间', 'danger')
                    return redirect(request.url)
                
                # 根据type查询现有记录
                measurement = BodyMeasurement.query.filter_by(
                    user_id=user.id,
                    type=type
                ).first()
                
                # 更新或创建记录
                if measurement:
                    measurement.height = height
                    measurement.weight = weight
                    measurement.body_fat = body_fat
                    measurement.muscle_mass = muscle_mass
                    # 只有更新最新数据时才修改measurement_date
                    if type == 'latest':
                        measurement.measurement_date = datetime.datetime.now()
                else:
                    measurement = BodyMeasurement(
                        user_id=user.id,
                        height=height,
                        weight=weight,
                        body_fat=body_fat,
                        muscle_mass=muscle_mass,
                        type=type
                    )
                    db.session.add(measurement)
                db.session.commit()
                
                if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify({
                        'success': True,
                        'message': '体测数据更新成功',
                        'updated_data': {
                            'height': measurement.height,
                            'weight': measurement.weight,
                            'body_fat': measurement.body_fat,
                            'muscle_mass': measurement.muscle_mass
                        }
                    })
                else:
                    flash('体测数据更新成功', 'success')
                    return redirect(url_for('update_measurement', type=type))
                
            except ValueError:
                flash('数据异常', 'danger')
                return redirect(request.url)
                
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'体测数据更新失败: {str(e)}')
            flash('数据异常', 'danger')
            return redirect(request.url)
    
    # 获取当前数据用于表单预填充
    if type == 'latest':
        current_data = BodyMeasurement.query.filter_by(
            user_id=user.id
        ).order_by(BodyMeasurement.measurement_date.desc()).first()
    else:
        current_data = BodyMeasurement.query.filter_by(
            user_id=user.id
        ).order_by(BodyMeasurement.measurement_date.asc()).first()
    
    # 获取目标数据
    goal_data = GoalMeasurement.query.filter_by(user_id=user.id).first()
    
    return render_template(
        'update_measurement.html',
        type=type,
        current_data=current_data,
        goal_data=goal_data
    )

@app.route('/update_goal', methods=['GET', 'POST'])
@login_required
def update_goal():
    user = db.session.get(User, session['user_id'])
    goal = GoalMeasurement.query.filter_by(user_id=user.id).first()
    
    if request.method == 'POST':
        try:
            # 获取表单数据
            min_height = float(request.form['min_height'])
            max_height = float(request.form['max_height'])
            min_weight = float(request.form['min_weight'])
            max_weight = float(request.form['max_weight'])
            min_body_fat = float(request.form['min_body_fat'])
            max_body_fat = float(request.form['max_body_fat'])
            min_muscle_mass = float(request.form['min_muscle_mass'])
            max_muscle_mass = float(request.form['max_muscle_mass'])
            
            # 验证范围值合理性
            if min_height > max_height:
                flash('最小身高不能大于最大身高', 'danger')
                return redirect(request.url)
            if min_weight > max_weight:
                flash('最小体重不能大于最大体重', 'danger')
                return redirect(request.url)
            if min_body_fat > max_body_fat:
                flash('最小体脂率不能大于最大体脂率', 'danger')
                return redirect(request.url)
            if min_muscle_mass > max_muscle_mass:
                flash('最小肌肉量不能大于最大肌肉量', 'danger')
                return redirect(request.url)
            
            # 更新或创建目标记录
            if goal:
                goal.min_height = min_height
                goal.max_height = max_height
                goal.min_weight = min_weight
                goal.max_weight = max_weight
                goal.min_body_fat = min_body_fat
                goal.max_body_fat = max_body_fat
                goal.min_muscle_mass = min_muscle_mass
                goal.max_muscle_mass = max_muscle_mass
                goal.last_updated = datetime.datetime.now()
            else:
                goal = GoalMeasurement(
                    user_id=user.id,
                    min_height=min_height,
                    max_height=max_height,
                    min_weight=min_weight,
                    max_weight=max_weight,
                    min_body_fat=min_body_fat,
                    max_body_fat=max_body_fat,
                    min_muscle_mass=min_muscle_mass,
                    max_muscle_mass=max_muscle_mass
                )
                db.session.add(goal)
            
            db.session.commit()
            flash('目标数据更新成功', 'success')
            return redirect(url_for('home'))
            
        except ValueError:
            flash('请输入有效的数值', 'danger')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'目标数据更新失败: {str(e)}')
            flash('更新失败，请稍后再试', 'danger')
    
    return render_template(
        'update_goal.html',
        goal_data=goal
    )

def update_course_statuses():
    """确保课程状态根据当前时间正确更新(动态属性会自动计算)"""
    # 只需查询所有课程即可触发状态重新计算
    Course.query.all()

# 课程列表和预约
@app.route('/courses')
@login_required
def courses():
    update_course_statuses()
    user = db.session.get(User, session['user_id'])
    
    # 强制清除默认日期参数
    args = request.args.copy()
    if 'start_date' in args and not args['start_date']:
        args.pop('start_date')
    if 'end_date' in args and not args['end_date']:
        args.pop('end_date')
    # 获取所有参数值并取最后一个非空值
    search_values = [v.strip() for v in args.getlist('search') if v.strip()]
    search = search_values[-1] if search_values else ''
    
    start_date_values = [v.strip() for v in args.getlist('start_date') if v.strip()]
    start_date = start_date_values[-1] if start_date_values else ''
    
    end_date_values = [v.strip() for v in args.getlist('end_date') if v.strip()]
    end_date = end_date_values[-1] if end_date_values else ''
    
    sort_values = [v.strip() for v in args.getlist('sort') if v.strip()]
    sort = sort_values[-1] if sort_values else 'time_desc'
    
    status_values = [v.strip() for v in args.getlist('status') if v.strip()]
    status_filter = status_values[-1] if status_values else 'current'
    
    query = Course.query
    
    # 搜索条件处理
    if search:
        search = search.strip()
        query = query.filter(
            db.or_(
                Course.name.ilike(f'%{search}%'),
                Course.instructor.ilike(f'%{search}%')
            )
        )

    # 日期范围筛选 - 只有当日期参数有效时才应用筛选
    try:
        if start_date and end_date:
            start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d')
            
            if start_date == end_date:
                # 同一天筛选，显示当天所有课程
                next_day = start_date + datetime.timedelta(days=1)
                query = query.filter(
                    Course.schedule >= start_date,
                    Course.schedule < next_day
                )
            else:
                # 正常日期范围筛选
                query = query.filter(
                    Course.schedule >= start_date,
                    Course.schedule <= end_date
                )
        elif start_date:
            start_date = datetime.datetime.strptime(start_date, '%Y-%m-%d')
            query = query.filter(Course.schedule >= start_date)
        elif end_date:
            end_date = datetime.datetime.strptime(end_date, '%Y-%m-%d')
            query = query.filter(Course.schedule <= end_date)
    except ValueError:
        # 日期格式无效时忽略筛选条件
        pass
    
    # 重建查询逻辑确保正确性
    now = datetime.datetime.now()
    
    # 根据状态筛选
    if status_filter == 'current':
        query = query.filter(
            db.and_(
                Course.is_deleted == False,  # 排除已删除课程
                db.or_(
                    Course.schedule > now,  # 未开始
                    db.and_(  # 进行中
                        Course.schedule <= now,
                        now < (Course.schedule + db.func.cast(Course.duration, db.Interval))
                    )
                )
            )
        )
    elif status_filter == 'expired':
        # 筛选已失效课程(包括已删除的)
        query = query.filter(
            db.or_(
                Course.is_deleted == True,  # 已删除的课程
                db.and_(
                    now > Course.schedule,  # 确保课程已经开始
                    now > (Course.schedule + db.func.cast(Course.duration, db.Interval))  # 确保课程已结束
                )
            )
        )
       
    elif status_filter == 'all':
        query = query  # 显示所有课程
    
    # 排序
    query = query.order_by(Course.schedule.desc() if sort != 'time_asc' else Course.schedule.asc())
    
    # 分页处理
    page = request.args.get('page', 1, type=int)
    per_page = 10
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    courses = pagination.items
 
    # 查询用户已预约的课程ID
    user_booked_courses = []
    if user.role != 'admin':
        bookings = Booking.query.filter_by(
            user_id=user.id,
            status='confirmed'
        ).all()
        user_booked_courses = [b.course_id for b in bookings]

    # 根据用户角色返回不同模板
    if user.role == 'admin':
        return render_template('admin_courses.html',
                            courses=courses,
                            pagination=pagination,
                            user=user,
                            status_filter=status_filter,
                            search=search,
                            start_date=start_date,
                            end_date=end_date,
                            sort=sort)
    else:
        return render_template('user_courses.html',
                            courses=courses,
                            pagination=pagination,
                            user=user,
                            status_filter=status_filter,
                            user_booked_courses=user_booked_courses,
                            search=search,
                            start_date=start_date,
                            end_date=end_date,
                            sort=sort)

@app.route('/my_bookings')
@login_required
def my_bookings():
    update_course_statuses()
    user = db.session.get(User, session['user_id'])
    # 获取用户已预约且未取消的课程，且课程未删除未过期
    bookings = db.session.query(Booking).join(Course).filter(
        Booking.user_id == user.id,
        Booking.status == 'confirmed',
        Course.is_deleted == False,
        db.or_(
            Course.schedule > datetime.datetime.now(),  # 未开始
            db.and_(  # 进行中
                Course.schedule <= datetime.datetime.now(),
                datetime.datetime.now() < (Course.schedule + db.func.cast(Course.duration, db.Interval))
            )
        )
    ).order_by(Booking.booking_time.desc()).all()
    
    return render_template('my_bookings.html',
                         bookings=bookings,
                         user=user)

@app.route('/history_bookings')
@login_required
def history_bookings():
    update_course_statuses()
    user = db.session.get(User, session['user_id'])
    # 获取用户所有预约记录，包括已取消的
    bookings = Booking.query.filter_by(
        user_id=user.id
    ).order_by(Booking.booking_time.desc()).all()
    
    return render_template('history_bookings.html',
                         bookings=bookings,
                         user=user)
    

# 预约课程
@app.route('/book_course/<int:course_id>', methods=['POST'])
@login_required
def book_course(course_id):
    try:
        course = Course.query.get_or_404(course_id)
        
        # 检查是否已经预约
        existing_booking = Booking.query.filter_by(
            user_id=session['user_id'],
            course_id=course_id,
            status='confirmed'
        ).first()

        if existing_booking:
            return jsonify({
                'success': False,
                'message': '您已经预约过该课程'
            }), 400
        
        # 检查课程是否已满
        if len(course.bookings) >= course.capacity:
            return jsonify({
                'success': False,
                'message': '该课程已满员'
            }), 400
        
        # 检查课程状态
        if course.status == 'ongoing':
            return jsonify({
                'success': False,
                'message': '课程正在进行中，无法预约'
            }), 400
        
        # 创建预约
        booking = Booking(
            user_id=session['user_id'],
            course_id=course_id
        )
        db.session.add(booking)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '课程预约成功'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'预约失败: {str(e)}'
        }), 500

# 取消预约
@app.route('/cancel_booking/<int:booking_id>', methods=['POST'])
@login_required
def cancel_booking(booking_id):
    try:
        booking = Booking.query.get_or_404(booking_id)
        
        # 检查是否是当前用户的预约
        if booking.user_id != session['user_id']:
            return jsonify({
                'success': False,
                'message': '无权取消此预约'
            }), 403
        
        booking.status = 'cancelled'
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '已取消课程预约'
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'取消预约失败: {str(e)}'
        }), 500

@app.route('/edit_course/<int:course_id>', methods=['GET', 'POST'])
@admin_required
def edit_course(course_id):
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name')
        instructor = request.form.get('instructor')
        date = request.form.get('date')
        time = request.form.get('time')
        duration = request.form.get('duration')
        capacity = request.form.get('capacity')
        description = request.form.get('description')
        
        # 基本验证
        if not all([name, instructor, date, time, duration, capacity]):
            flash('请填写所有必填字段', 'error')
            return render_template('edit_course.html',
                                course=course,
                                schedule_date=date,
                                schedule_time=time)
        
        try:
            duration = int(duration)
            capacity = int(capacity)
            
            # 验证时长
            if duration <= 0 or duration > 240:
                flash('课程时长必须在1-240分钟之间', 'error')
                return render_template('edit_course.html',
                                    course=course,
                                    schedule_date=date,
                                    schedule_time=time)
            
            # 验证容量
            if capacity <= 0 or capacity > 100:
                flash('课程容量必须在1-100之间', 'error')
                return render_template('edit_course.html',
                                    course=course,
                                    schedule_date=date,
                                    schedule_time=time)
            
            # 检查当前预约人数是否超过新容量
            current_bookings = len([b for b in course.bookings if b.status == 'confirmed'])
            if capacity < current_bookings:
                flash(f'当前已有{current_bookings}人预约，容量不能小于此数值', 'error')
                return render_template('edit_course.html',
                                    course=course,
                                    schedule_date=date,
                                    schedule_time=time)
            
            # 合并日期和时间
            try:
                schedule_str = f"{date} {time}"
                schedule = datetime.datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
                
                # 验证课程时间是否在当前时间之后
                if schedule <= datetime.datetime.now():
                    flash('课程时间必须晚于当前时间', 'error')
                    return render_template('edit_course.html',
                                        course=course,
                                        schedule_date=date,
                                        schedule_time=time)
                
                # 更新课程数据
                course.name = name
                course.instructor = instructor
                course.schedule = schedule
                course.duration = duration
                course.capacity = capacity
                course.description = description
                
                # 确保数据库变更被提交
                db.session.commit()
                flash('课程更新成功', 'success')
                return redirect(url_for('edit_course', course_id=course.id))
                
            except ValueError:
                flash('日期时间格式不正确，请使用YYYY-MM-DD和HH:MM格式', 'error')
                return render_template('edit_course.html',
                                    course=course,
                                    schedule_date=date,
                                    schedule_time=time)
                
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'课程更新失败: {str(e)}')
            flash(f'保存失败: {str(e)}', 'error')
            return render_template('edit_course.html',
                                course=course,
                                schedule_date=date,
                                schedule_time=time)
    
    # GET请求显示表单
    return render_template('edit_course.html', 
                         course=course,
                         schedule_date=course.schedule.strftime('%Y-%m-%d'),
                         schedule_time=course.schedule.strftime('%H:%M'))

@app.route('/delete_course/<int:course_id>', methods=['POST'])
@admin_required
def delete_course(course_id):
    try:
        # 检查课程是否存在
        course = Course.query.get(course_id)
        if not course:
            flash('课程不存在', 'error')
            return redirect(url_for('courses'))

        # 打印调试信息
        print(f"标记删除课程: ID={course_id}, 名称={course.name}")

        # 标记课程为已删除
        course.is_deleted = True
        db.session.commit()
        
        flash('课程已标记为删除', 'success')
        print(f"课程标记删除成功: ID={course_id}")

    except Exception as e:
        db.session.rollback()
        error_msg = f'标记删除课程失败: {str(e)}'
        flash(error_msg, 'error')
        print(f"标记删除课程异常: {error_msg}")
        print(traceback.format_exc())
        
    return redirect(url_for('courses'))

@app.route('/admin_coaches')
@admin_required
def admin_coaches():
    # 清除所有flash消息
    flash('', '')  
    coaches = Coach.query.order_by(Coach.created_at.desc()).all()
    return render_template('admin_coaches.html', coaches=coaches)

@app.route('/edit_coach/<int:coach_id>', methods=['GET', 'POST'])
@admin_required
def edit_coach(coach_id):
    coach = Coach.query.get_or_404(coach_id)
    
    if request.method == 'POST':
        try:
            # 更新基本信息
            coach.name = request.form.get('name')
            coach.age = int(request.form.get('age')) if request.form.get('age') else None
            coach.specialty = request.form.get('specialty')
            coach.description = request.form.get('description')
            
            # 处理图片上传
            image = request.files.get('image')
            if image and image.filename:
                # 删除旧图片
                if coach.image_url:
                    old_image_path = os.path.join(app.root_path, 'static', coach.image_url.split('/static/')[-1])
                    if os.path.exists(old_image_path):
                        os.remove(old_image_path)
                
                # 保存新图片
                filename = f"coach_{secrets.token_hex(8)}.{image.filename.split('.')[-1]}"
                image_path = os.path.join(app.root_path, 'static', 'images', filename)
                image.save(image_path)
                coach.image_url = url_for('static', filename=f'images/{filename}')
            
            db.session.commit()
            return redirect(url_for('edit_coach', 
                                 coach_id=coach.id,
                                 flash='教练信息更新成功',
                                 type='success'))
            
        except ValueError:
            flash('年龄必须是数字', 'error')
        except Exception as e:
            db.session.rollback()
            flash(f'更新失败: {str(e)}', 'error')
    
    return render_template('edit_coach.html', coach=coach)

@app.route('/delete_coach/<int:coach_id>', methods=['POST'])
@admin_required
def delete_coach(coach_id):
    try:
        # 查找教练
        coach = Coach.query.get_or_404(coach_id)
        
        # 获取图片路径
        image_path = None
        if coach.image_url:
            # 从URL中提取文件名
            filename = coach.image_url.split('/')[-1]
            image_path = os.path.join(app.root_path, 'static', 'images', filename)
        
        # 删除教练
        db.session.delete(coach)
        db.session.commit()
        
        # 删除图片文件
        if image_path and os.path.exists(image_path):
            try:
                os.remove(image_path)
            except Exception as e:
                app.logger.warning(f'删除教练图片失败: {str(e)}')
        
        flash('教练删除成功', 'delete')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f'删除教练失败: {str(e)}')
        flash('删除教练失败，请重试', 'error')
    
    return redirect(url_for('admin_coaches'))

@app.route('/add_coach', methods=['GET', 'POST'])
@admin_required
def add_coach():
    if request.method == 'POST':
        # 获取表单数据
        name = request.form.get('name')
        age = request.form.get('age')
        specialty = request.form.get('specialty')
        description = request.form.get('description')
        image = request.files.get('image')
        
        # 基本验证
        if not name:
            flash('教练姓名不能为空', 'error')
            return render_template('add_coach.html')
        
        try:
            # 处理年龄
            age = int(age) if age else None
            
            # 处理图片上传
            image_url = None
            if image and image.filename:
                filename = f"coach_{secrets.token_hex(8)}.{image.filename.split('.')[-1]}"
                image_path = os.path.join(app.root_path, 'static', 'images', filename)
                image.save(image_path)
                image_url = url_for('static', filename=f'images/{filename}')
            
            # 创建教练
            coach = Coach(
                name=name,
                age=age,
                specialty=specialty,
                description=description,
                image_url=image_url
            )
            db.session.add(coach)
            db.session.commit()
            
            flash('教练添加成功', 'success')
            return render_template('add_coach.html')
            
        except ValueError:
            flash('年龄必须是数字', 'error')
            return render_template('add_coach.html')
        except Exception as e:
            db.session.rollback()
            app.logger.error(f'添加教练失败: {str(e)}')
            flash(f'添加失败: {str(e)}', 'error')
            return render_template('add_coach.html')
    
    # GET请求显示表单
    return render_template('add_coach.html')

@app.route('/add_course', methods=['GET', 'POST'])
@admin_required
def add_course():
    if request.method == 'POST':
        try:
            # 获取表单数据
            name = request.form.get('name')
            instructor = request.form.get('instructor')
            date = request.form.get('date')
            time = request.form.get('time')
            duration = request.form.get('duration')
            description = request.form.get('description')
            
            # 验证必填字段
            if not all([name, instructor, date, time, duration]):
                flash('请填写所有必填字段', 'error')
                return redirect(url_for('add_course'))
            
            # 合并日期和时间
            schedule_str = f"{date} {time}"
            schedule = datetime.datetime.strptime(schedule_str, "%Y-%m-%d %H:%M")
            
            # 获取并验证人数限制
            capacity = request.form.get('capacity')
            if not capacity or not capacity.isdigit():
                flash('请输入有效的人数限制', 'error')
                return redirect(url_for('add_course'))
            
            # 创建课程
            new_course = Course(
                name=name,
                instructor=instructor,
                schedule=schedule,
                duration=int(duration),
                description=description,
                capacity=int(capacity)
            )
            
            db.session.add(new_course)
            db.session.commit()
            flash('课程添加成功', 'success')
            return redirect(url_for('add_course', saved='true'))
            
        except ValueError as e:
            flash('日期时间格式不正确', 'error')
            return redirect(url_for('add_course', saved='false'))
        except Exception as e:
            db.session.rollback()
            flash('添加课程失败: ' + str(e), 'error')
            return redirect(url_for('add_course', saved='false'))
    
    # GET请求显示表单
    return render_template('add_course.html')

@app.route('/view_coaches')
@login_required
def view_coaches():
    """用户查看教练列表"""
    try:
        # 获取所有教练
        coaches = Coach.query.order_by(Coach.created_at.desc()).all()
        
        # 获取当前用户已关注的教练ID列表
        user_id = session['user_id']
        followed_coach_ids = [f.coach_id for f in 
                            UserCoachFollow.query.filter_by(user_id=user_id).all()]
        
        return render_template(
            'view_coaches.html',
            coaches=coaches,
            followed_coach_ids=followed_coach_ids
        )
    except Exception as e:
        app.logger.error(f'获取教练列表失败: {str(e)}')
        flash('获取教练列表失败', 'danger')
        return redirect(url_for('home'))

@app.route('/qualification')
def qualification():
    """展示健身房资质证书页面"""
    return render_template('qualification.html')

@app.route('/test_db')
def test_db():
    try:
        db.session.execute('SELECT 1')
        return 'Database connection OK'
    except Exception as e:
        return f'Database error: {str(e)}'

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=9000, debug=True)

