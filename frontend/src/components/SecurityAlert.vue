<template>
  <Teleport to="body">
    <Transition name="security-alert">
      <div v-if="visible" class="security-alert-overlay" @click.self="close">
        <div class="security-alert-modal">
          <div class="alert-icon">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 9V13M12 17H12.01M21 12C21 16.9706 16.9706 21 12 21C7.02944 21 3 16.9706 3 12C3 7.02944 7.02944 3 12 3C16.9706 3 21 7.02944 21 12Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
          </div>
          
          <h2 class="alert-title">⚠️ 安全警告</h2>
          
          <p class="alert-message">{{ message }}</p>
          
          <div v-if="details" class="alert-details">
            <div v-if="details.attack_type" class="detail-item">
              <span class="detail-label">攻击类型：</span>
              <span class="detail-value attack-type">{{ details.attack_type }}</span>
            </div>
            <div v-if="details.ip" class="detail-item">
              <span class="detail-label">您的IP：</span>
              <span class="detail-value">{{ details.ip }}</span>
            </div>
            <div v-if="details.attempts_left !== undefined" class="detail-item">
              <span class="detail-label">剩余尝试次数：</span>
              <span class="detail-value" :class="{ warning: details.attempts_left <= 2 }">
                {{ details.attempts_left }}
              </span>
            </div>
            <div v-if="details.remaining_seconds" class="detail-item">
              <span class="detail-label">封禁剩余时间：</span>
              <span class="detail-value">{{ formatTime(details.remaining_seconds) }}</span>
            </div>
          </div>
          
          <div class="alert-warning">
            <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M12 9V13M12 17H12.01M12 3L20.39 18C20.5495 18.2961 20.5406 18.6539 20.3665 18.9417C20.1923 19.2295 19.8789 19.4048 19.54 19.4H4.46C4.12112 19.4048 3.80772 19.2295 3.63353 18.9417C3.45934 18.6539 3.45046 18.2961 3.61 18L12 3Z" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <span>您的操作已被记录，请勿尝试恶意行为</span>
          </div>
          
          <button class="alert-button" @click="close">我知道了</button>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script>
import { ref, onMounted, onUnmounted } from 'vue'

export default {
  name: 'SecurityAlert',
  setup() {
    const visible = ref(false)
    const message = ref('')
    const details = ref(null)
    
    const handleSecurityError = (event) => {
      const { error, response } = event.detail || {}
      
      if (response && response.error === 'security_violation') {
        message.value = response.message || '检测到危险操作'
        details.value = response.details || null
        visible.value = true
      } else if (response && response.error === 'access_denied') {
        message.value = response.message || '您的IP已被封禁'
        details.value = response.details || null
        visible.value = true
      }
    }
    
    const close = () => {
      visible.value = false
    }
    
    const formatTime = (seconds) => {
      const mins = Math.floor(seconds / 60)
      const secs = seconds % 60
      return `${mins}分${secs}秒`
    }
    
    onMounted(() => {
      window.addEventListener('security-error', handleSecurityError)
    })
    
    onUnmounted(() => {
      window.removeEventListener('security-error', handleSecurityError)
    })
    
    return {
      visible,
      message,
      details,
      close,
      formatTime
    }
  }
}
</script>

<style scoped>
.security-alert-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  backdrop-filter: blur(4px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}

.security-alert-modal {
  background: linear-gradient(135deg, #1a1f35 0%, #0d1321 100%);
  border: 1px solid #ff4d4f;
  border-radius: 16px;
  padding: 32px;
  max-width: 420px;
  width: 90%;
  text-align: center;
  box-shadow: 0 20px 60px rgba(255, 77, 79, 0.3);
}

.alert-icon {
  width: 64px;
  height: 64px;
  margin: 0 auto 20px;
  color: #ff4d4f;
  animation: pulse 2s infinite;
}

.alert-icon svg {
  width: 100%;
  height: 100%;
}

@keyframes pulse {
  0%, 100% {
    transform: scale(1);
    opacity: 1;
  }
  50% {
    transform: scale(1.1);
    opacity: 0.8;
  }
}

.alert-title {
  color: #ff4d4f;
  font-size: 1.5rem;
  margin: 0 0 16px;
  font-weight: bold;
}

.alert-message {
  color: #e0e6f0;
  font-size: 1.1rem;
  margin: 0 0 20px;
}

.alert-details {
  background: rgba(255, 77, 79, 0.1);
  border-radius: 8px;
  padding: 16px;
  margin-bottom: 20px;
}

.detail-item {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  border-bottom: 1px solid rgba(255, 77, 79, 0.2);
}

.detail-item:last-child {
  border-bottom: none;
}

.detail-label {
  color: #8ba4c7;
}

.detail-value {
  color: #e0e6f0;
  font-weight: 500;
}

.detail-value.attack-type {
  color: #ff4d4f;
}

.detail-value.warning {
  color: #faad14;
  font-weight: bold;
}

.alert-warning {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #faad14;
  font-size: 0.9rem;
  margin-bottom: 24px;
  padding: 12px;
  background: rgba(250, 173, 20, 0.1);
  border-radius: 8px;
}

.alert-warning svg {
  width: 20px;
  height: 20px;
  flex-shrink: 0;
}

.alert-button {
  background: linear-gradient(135deg, #ff4d4f, #cf1322);
  border: none;
  color: #fff;
  padding: 12px 48px;
  border-radius: 8px;
  font-size: 1rem;
  cursor: pointer;
  transition: all 0.3s ease;
}

.alert-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(255, 77, 79, 0.4);
}

.security-alert-enter-active,
.security-alert-leave-active {
  transition: all 0.3s ease;
}

.security-alert-enter-from,
.security-alert-leave-to {
  opacity: 0;
}

.security-alert-enter-from .security-alert-modal,
.security-alert-leave-to .security-alert-modal {
  transform: scale(0.9);
}

@media (max-width: 768px) {
  .security-alert-modal {
    padding: 24px 20px;
    margin: 20px;
    width: 95%;
  }

  .alert-icon {
    width: 48px;
    height: 48px;
  }

  .alert-title {
    font-size: 1.25rem;
  }

  .alert-message {
    font-size: 1rem;
  }

  .alert-details {
    padding: 12px;
  }

  .detail-item {
    flex-direction: column;
    gap: 4px;
    padding: 6px 0;
  }

  .alert-warning {
    font-size: 0.85rem;
    padding: 10px;
  }

  .alert-button {
    width: 100%;
    padding: 14px;
  }
}
</style>
