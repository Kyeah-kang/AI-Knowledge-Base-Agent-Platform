// 认证状态管理

import { create } from "zustand";
import {
  getAccessToken,
  setAccessToken,
  setRefreshToken,
  setUserInfo,
  clearAuth,
  getUserInfo,
} from "../utils/token";

interface User {
  id: number;
  username: string;
  email: string;
  is_admin: boolean;
}

interface AuthState {
  user: User | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  login: (tokenData: {
    access_token: string;
    refresh_token: string;
    user: User;
  }) => void;
  setUser: (user: User) => void;
  logout: () => void;
  init: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!getAccessToken(),
  isAdmin: false,

  login: (tokenData) => {
    setAccessToken(tokenData.access_token);
    setRefreshToken(tokenData.refresh_token);
    setUserInfo(tokenData.user);
    set({
      user: tokenData.user,
      isAuthenticated: true,
      isAdmin: tokenData.user.is_admin,
    });
  },

  setUser: (user) => {
    setUserInfo(user);
    set({ user, isAdmin: user.is_admin });
  },

  logout: () => {
    clearAuth();
    set({ user: null, isAuthenticated: false, isAdmin: false });
  },

  init: () => {
    const user = getUserInfo();
    if (user) {
      set({ user, isAuthenticated: true, isAdmin: user.is_admin });
    }
  },
}));
