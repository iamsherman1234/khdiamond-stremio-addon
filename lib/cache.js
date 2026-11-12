"use strict";

class SimpleCache {
  constructor(defaultTtlSeconds = 3600) {
    this.store = new Map();
    this.defaultTtlMs = defaultTtlSeconds * 1000;
  }

  get(key) {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return null;
    }
    return entry.value;
  }

  set(key, value, ttlSeconds) {
    const ttlMs = (ttlSeconds !== undefined ? ttlSeconds : this.defaultTtlMs / 1000) * 1000;
    this.store.set(key, {
      value,
      expiresAt: Date.now() + ttlMs,
    });
  }

  has(key) {
    return this.get(key) !== null;
  }

  delete(key) {
    return this.store.delete(key);
  }

  clear() {
    this.store.clear();
  }
}

module.exports = { SimpleCache };
