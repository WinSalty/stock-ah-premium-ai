import { requestJson } from './client';
import type {
  AuthTokenResponse,
  InvitationCreateRequest,
  InvitationResponse,
  LoginRequest,
  ProfileUpdateRequest,
  RegisterRequest,
  UserInfo,
  UserUpdateRequest
} from '../types/domain';

export function login(payload: LoginRequest) {
  return requestJson<AuthTokenResponse>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function register(payload: RegisterRequest) {
  return requestJson<AuthTokenResponse>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function fetchCurrentUser() {
  return requestJson<UserInfo>('/api/auth/me');
}

export function createInvitation(payload: InvitationCreateRequest) {
  return requestJson<InvitationResponse>('/api/invitations', {
    method: 'POST',
    body: JSON.stringify(payload)
  });
}

export function fetchInvitations() {
  return requestJson<InvitationResponse[]>('/api/invitations');
}

export function fetchUsers() {
  return requestJson<UserInfo[]>('/api/auth/users');
}

export function updateUser(userId: number, payload: UserUpdateRequest) {
  return requestJson<UserInfo>(`/api/auth/users/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  });
}

export function updateProfile(payload: ProfileUpdateRequest) {
  return requestJson<UserInfo>('/api/auth/profile', {
    method: 'PUT',
    body: JSON.stringify(payload)
  });
}
