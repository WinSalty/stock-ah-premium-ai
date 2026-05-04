import { requestJson } from './client';
import type {
  AuthTokenResponse,
  InvitationCreateRequest,
  InvitationResponse,
  LoginRequest,
  RegisterRequest,
  UserInfo
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
