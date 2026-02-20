import pytest
from app import app, db, User
from werkzeug.security import generate_password_hash

@pytest.fixture
def client():
    """Create a test client for the app."""
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    
    with app.app_context():
        db.create_all()
        yield app.test_client()
        db.session.remove()
        db.drop_all()

def test_welcome_page(client):
    """Test that the welcome page loads."""
    response = client.get('/')
    assert response.status_code == 200

def test_login_page(client):
    """Test that the login page loads."""
    response = client.get('/login')
    assert response.status_code == 200

def test_register_page(client):
    """Test that the register page loads."""
    response = client.get('/register')
    assert response.status_code == 200

def test_successful_login(client):
    """Test successful login."""
    with app.app_context():
        # Create a test user
        user = User(
            username='testuser',
            password=generate_password_hash('TestPass123', method='pbkdf2:sha256', salt_length=16),
            role='user'
        )
        db.session.add(user)
        db.session.commit()
    
    # First, get the login page to extract the CSRF token
    response = client.get('/login')
    assert response.status_code == 200
    
    # Extract CSRF token from the response
    csrf_token = None
    if b'csrf_token' in response.data:
        # Parse the HTML to find the CSRF token value
        import re
        match = re.search(b'name="csrf_token"\s+type="hidden"\s+value="([^"]+)"', response.data)
        if match:
            csrf_token = match.group(1).decode('utf-8')
    
    # Login with CSRF token
    response = client.post('/login', data={
        'username': 'testuser',
        'password': 'TestPass123',
        'csrf_token': csrf_token
    }, follow_redirects=True)
    
    assert response.status_code == 200

def test_logout(client):
    """Test logout functionality."""
    with app.app_context():
        user = User(
            username='testuser2',
            password=generate_password_hash('TestPass123', method='pbkdf2:sha256', salt_length=16),
            role='user'
        )
        db.session.add(user)
        db.session.commit()
    
    # Login first
    client.post('/login', data={
        'username': 'testuser2',
        'password': 'TestPass123'
    })
    
    # Then logout
    response = client.get('/logout', follow_redirects=True)
    assert response.status_code == 200
