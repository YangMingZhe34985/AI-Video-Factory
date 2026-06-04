import request from './request'

export function register(username, email, password) {
  return request.post('/auth/register', { username, email, password })
}

export function login(username, password) {
  return request.post('/auth/login', { username, password })
}

export function me() {
  return request.get('/auth/me')
}

export function refresh() {
  const refreshToken = localStorage.getItem('refresh_token')
  return request.post('/auth/refresh', {}, {
    headers: { Authorization: `Bearer ${refreshToken}` },
  })
}