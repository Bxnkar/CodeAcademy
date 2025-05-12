from flask import Flask, render_template, request, redirect, url_for, flash, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
from moviepy.editor import VideoFileClip
import imageio

class VideoStreamingError(Exception):
    """Base exception class for video streaming application"""
    pass

class VideoUploadError(VideoStreamingError):
    """Exception raised for video upload related errors"""
    pass

class ThumbnailGenerationError(VideoStreamingError):
    """Exception raised for thumbnail generation errors"""
    pass

class AuthenticationError(VideoStreamingError):
    """Exception raised for authentication related errors"""
    pass

class VideoService:
    """Service class for video-related operations"""
    
    def __init__(self, app):
        self.app = app
        self.upload_folder = app.config['UPLOAD_FOLDER']
        self.thumbnail_folder = app.config['THUMBNAIL_FOLDER']
        self.allowed_extensions = app.config['ALLOWED_EXTENSIONS']
    
    def generate_thumbnail(self, video_path, thumbnail_path):
        """Generate thumbnail from video file"""
        try:
            try:
                video = VideoFileClip(video_path)
                time = min(1, video.duration)
                video.save_frame(thumbnail_path, t=time)
                video.close()
                return True
            except Exception as e:
                print(f"VideoFileClip failed: {e}")
                # Fallback to imageio if VideoFileClip fails
                reader = imageio.get_reader(video_path)
                first_frame = reader.get_data(0)
                imageio.imwrite(thumbnail_path, first_frame)
                reader.close()
                return True
        except Exception as e:
            print(f"Thumbnail generation failed: {e}")
            raise ThumbnailGenerationError(f"Failed to generate thumbnail: {str(e)}")
    
    def save_video(self, video_file, title):
        """Save uploaded video and generate thumbnail"""
        try:
            if not video_file or video_file.filename == '':
                raise VideoUploadError("No video file selected")
            
            if not self._is_allowed_file(video_file.filename):
                raise VideoUploadError("Invalid file type. Allowed formats: MP4, AVI, MOV, WMV, FLV, MKV")
            
            filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{video_file.filename}"
            video_path = os.path.join(self.upload_folder, filename)
            video_file.save(video_path)
            
            thumbnail_filename = f"thumb_{filename.rsplit('.', 1)[0]}.jpg"
            thumbnail_path = os.path.join(self.thumbnail_folder, thumbnail_filename)
            
            if self.generate_thumbnail(video_path, thumbnail_path):
                return filename, thumbnail_filename
            raise ThumbnailGenerationError("Failed to generate thumbnail")
            
        except Exception as e:
            # Clean up if something goes wrong
            if os.path.exists(video_path):
                os.remove(video_path)
            raise VideoUploadError(f"Failed to upload video: {str(e)}")
    
    def _is_allowed_file(self, filename):
        """Check if file extension is allowed"""
        return '.' in filename and \
               filename.rsplit('.', 1)[1].lower() in self.allowed_extensions

class UserService:
    """Service class for user-related operations"""
    
    def __init__(self, db):
        self.db = db
    
    def create_user(self, username, password):
        """Create a new user"""
        try:
            if len(password) < 8:
                raise AuthenticationError("Password must be at least 8 characters long")
            
            if User.query.filter_by(username=username).first():
                raise AuthenticationError("Username already exists")
            
            user = User(
                username=username,
                password_hash=generate_password_hash(password)
            )
            self.db.session.add(user)
            self.db.session.commit()
            return user
        except Exception as e:
            self.db.session.rollback()
            raise AuthenticationError(f"Failed to create user: {str(e)}")
    
    def authenticate_user(self, username, password):
        """Authenticate user"""
        try:
            user = User.query.filter_by(username=username).first()
            if not user or not check_password_hash(user.password_hash, password):
                raise AuthenticationError("Invalid username or password")
            return user
        except Exception as e:
            raise AuthenticationError(f"Authentication failed: {str(e)}")

app = Flask(__name__)
app.config['SECRET_KEY'] = '2404118'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///video_streaming.db'
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['THUMBNAIL_FOLDER'] = 'static/thumbnails'
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'mp4', 'avi', 'mov', 'wmv', 'flv', 'mkv'}

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Initialize services
video_service = VideoService(app)
user_service = UserService(db)

# Ensure upload folders exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['THUMBNAIL_FOLDER'], exist_ok=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)
    is_superuser = db.Column(db.Boolean, default=False)

class Video(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    thumbnail_filename = db.Column(db.String(255))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.errorhandler(VideoStreamingError)
def handle_video_streaming_error(error):
    """Handle custom exceptions"""
    flash(str(error))
    return redirect(request.referrer or url_for('home'))

@app.route('/')
@login_required
def home():
    try:
        search_query = request.args.get('search', '')
        if search_query:
            videos = Video.query.filter(Video.title.ilike(f'%{search_query}%')).order_by(Video.upload_date.desc()).all()
        else:
            videos = Video.query.order_by(Video.upload_date.desc()).all()
        return render_template('home.html', videos=videos, search_query=search_query)
    except Exception as e:
        flash(f"Error loading videos: {str(e)}")
        return redirect(url_for('home'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            user = user_service.create_user(username, password)
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except AuthenticationError as e:
            flash(str(e))
            return redirect(url_for('register'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        try:
            username = request.form.get('username')
            password = request.form.get('password')
            user = user_service.authenticate_user(username, password)
            login_user(user)
            return redirect(url_for('home'))
        except AuthenticationError as e:
            flash(str(e))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if not current_user.is_superuser:
        flash('Only superusers can upload videos')
        return redirect(url_for('home'))
    
    if request.method == 'POST':
        try:
            video = request.files['video']
            title = request.form.get('title')
            
            filename, thumbnail_filename = video_service.save_video(video, title)
            
            new_video = Video(
                title=title,
                filename=filename,
                thumbnail_filename=thumbnail_filename
            )
            db.session.add(new_video)
            db.session.commit()
            flash('Video uploaded successfully!')
            return redirect(url_for('home'))
        except VideoUploadError as e:
            flash(str(e))
            return redirect(request.url)
    
    return render_template('upload.html')

@app.route('/delete_video/<int:video_id>')
@login_required
def delete_video(video_id):
    if not current_user.is_superuser:
        flash('Only superusers can delete videos')
        return redirect(url_for('home'))
    
    try:
        video = Video.query.get_or_404(video_id)
        video_path = os.path.join(app.config['UPLOAD_FOLDER'], video.filename)
        thumbnail_path = os.path.join(app.config['THUMBNAIL_FOLDER'], video.thumbnail_filename)
        
        if os.path.exists(video_path):
            os.remove(video_path)
        if os.path.exists(thumbnail_path):
            os.remove(thumbnail_path)
            
        db.session.delete(video)
        db.session.commit()
        flash('Video deleted successfully!')
    except Exception as e:
        flash(f'Error deleting video: {str(e)}')
    
    return redirect(url_for('home'))

@app.route('/video/<int:video_id>')
@login_required
def watch_video(video_id):
    video = Video.query.get_or_404(video_id)
    return render_template('watch.html', video=video)

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_superuser:
        flash('Access denied. Only superusers can access the admin dashboard.')
        return redirect(url_for('home'))
    
    users = User.query.all()
    videos = Video.query.order_by(Video.upload_date.desc()).all()
    return render_template('admin_dashboard.html', users=users, videos=videos)

@app.route('/delete_user/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_superuser:
        flash('Access denied. Only superusers can delete users.')
        return redirect(url_for('home'))
    
    user = User.query.get_or_404(user_id)
    if user.is_superuser:
        flash('Cannot delete superuser accounts.')
        return redirect(url_for('admin_dashboard'))
    
    try:
        db.session.delete(user)
        db.session.commit()
        flash('User deleted successfully!')
    except Exception as e:
        flash('Error deleting user')
    
    return redirect(url_for('admin_dashboard'))

if __name__ == '__main__':
    with app.app_context():
        try:
            db.create_all()
            
            if not User.query.filter_by(username='piyu').first():
                superuser = User(
                    username='piyu',
                    password_hash=generate_password_hash('piyu'),
                    is_superuser=True
                )
                db.session.add(superuser)
                db.session.commit()
                print("Superuser created successfully!")
            else:
                print("Superuser already exists!")
                
            print("Database initialized successfully!")
        except Exception as e:
            print(f"Error initializing database: {e}")
            db.session.rollback()
            
    app.run(debug=True) 