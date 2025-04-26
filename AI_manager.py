from PyQt6.QtCore import QObject, pyqtSignal, QUuid
from AI_professor_chat import AIProfessorChat
from threads import AIResponseThread
from TTS_manager import TTSManager
from voice_input import VoiceInput
from rag_retriever import RagRetriever
import os

class AIManager(QObject):
    """
    AI管理类 - 处理所有AI相关的功能
    
    包括:
    - AI对话逻辑
    - 语音识别
    - TTS语音合成
    - RAG检索增强生成
    """
    # 信号定义
    ai_response_ready = pyqtSignal(str)       # AI回复准备好信号
    vad_started = pyqtSignal()                # 语音活动开始信号
    vad_stopped = pyqtSignal()                # 语音活动结束信号  
    voice_text_received = pyqtSignal(str)     # 接收到语音文本信号
    voice_error = pyqtSignal(str)             # 语音错误信号
    voice_ready = pyqtSignal()                # 语音系统就绪信号
    voice_device_switched = pyqtSignal(bool)  # 语音设备切换状态信号
    ai_sentence_ready = pyqtSignal(str, str)  # 单句AI回复准备好信号（内容, 请求ID）
    ai_generation_cancelled = pyqtSignal()    # AI生成被取消信号
    
    def __init__(self):
        """初始化AI管理器"""
        super().__init__()
        
        # 初始化AI聊天助手
        self._init_ai_assistant()
        
        # 初始化TTS管理器
        self.tts_manager = TTSManager()
        # 连接TTS播放开始信号
        self.tts_manager.tts_playback_started.connect(self._on_tts_playback_started)
        # 连接TTS音频实际播放开始信号
        self.tts_manager.tts_audio_playback_started.connect(self._on_tts_audio_playback_started)
        
        # 缓存待显示的句子
        self.pending_sentences = {}
        
        # 语音输入对象将在init_voice_recognition中初始化
        self.voice_input = None
        self.data_manager = None  # 将在later设置
        
        # 添加状态标志来跟踪是否有正在进行的AI生成
        self.is_generating_response = False
        
        # 当前活动的请求ID
        self.current_request_id = None

        # 添加累积响应变量
        self.accumulated_response = ""
        
        # 添加TTS启用标志
        self.tts_enabled = True
    
    def set_data_manager(self, data_manager):
        """设置数据管理器引用"""
        self.data_manager = data_manager
    
    def _init_ai_assistant(self):
        """初始化AI聊天助手和响应线程"""
        self.ai_chat = AIProfessorChat()
        self.ai_response_thread = AIResponseThread(self.ai_chat)
        self.ai_response_thread.response_ready.connect(self._on_ai_response_ready)
        # 连接新的单句信号
        self.ai_response_thread.sentence_ready.connect(self._on_ai_sentence_ready)
    
    def init_voice_recognition(self, input_device_index=0):
        """初始化语音识别系统"""
        if self.voice_input is not None:
            return True  # 已经初始化
        
        try:
            # 创建语音输入对象
            self.voice_input = VoiceInput(input_device_index)
            
            # 连接信号
            self.voice_input.text_received.connect(self._on_voice_text_received)
            self.voice_input.vad_started.connect(self._on_vad_started)
            self.voice_input.vad_stopped.connect(self._on_vad_stopped)
            self.voice_input.error_occurred.connect(self._on_voice_error)
            self.voice_input.initialization_complete.connect(self._on_voice_init_complete)
            
            # 开始后台初始化
            self.voice_input.initialize()
            
            return True
        except Exception as e:
            print(f"初始化语音识别失败: {str(e)}")
            return False

    def _on_voice_init_complete(self, success):
        """语音初始化完成回调"""
        if success:
            self.voice_ready.emit()
        else:
            self.voice_error.emit("语音系统初始化失败")
    
    def cancel_current_response(self):
        """取消当前正在生成的AI响应"""
        print("取消当前的AI响应...")
        
        # 停止TTS播放并清除与当前请求相关的所有待处理TTS
        if self.current_request_id:
            self.tts_manager.cancel_request_id(self.current_request_id)
        else:
            self.tts_manager.stop_playing()  # 旧版兼容
        
        # 处理已收集的部分响应
        # 只有当有实际内容时才添加到历史记录
        if self.accumulated_response and self.accumulated_response.strip():
            print(f"保存已生成的部分响应到对话历史: {self.accumulated_response[:30]}...")
            # 将已生成的部分添加到对话历史
            if hasattr(self.ai_chat, 'conversation_history'):
                # 添加到对话历史
                self.ai_chat.conversation_history.append({
                    "role": "assistant", 
                    "content": self.accumulated_response
                })
        # 无论是否添加到历史，都重置累积响应
        self.accumulated_response = ""
        
        # 清空待处理的句子
        self.pending_sentences.clear()
        
        # 中断AI响应线程
        if self.ai_response_thread.isRunning():
            print("正在停止AI生成...")
            self.ai_response_thread.requestInterruption()
            self.ai_response_thread.wait(1000)  # 等待最多1秒
            
            # 发出取消信号，以便UI清理loading bubble
            self.is_generating_response = False
            self.ai_generation_cancelled.emit()
            
            # 清除当前请求ID
            self.current_request_id = None
    
    def is_busy(self):
        """检查是否有AI响应正在生成或TTS正在播放"""
        return self.is_generating_response or not self.tts_manager.is_queue_empty()
    
    def get_ai_response(self, query, paper_id=None, visible_content=None):
        """获取AI对用户查询的响应"""
        try:
            # 如果已经有正在生成的响应，先取消它
            if self.is_generating_response:
                print("[AIManager] Cancelling existing response before starting new one")
                self.cancel_current_response()
            
            # 确保线程不在运行状态
            if self.ai_response_thread.isRunning():
                print("等待上一个AI响应线程结束...")
                self.ai_response_thread.requestInterruption()
                self.ai_response_thread.wait(1000)  # 等待最多1秒
                
                # 如果线程仍在运行，创建新的线程
                if self.ai_response_thread.isRunning():
                    print("创建新的AI响应线程...")
                    self._init_ai_assistant()
            
            # 生成新的请求ID
            request_id = str(QUuid.createUuid().toString(QUuid.StringFormat.Id128))
            self.current_request_id = request_id
            print(f"创建新的AI请求，ID: {request_id}")
            
            # 确保有论文上下文(如果必要)
            if not paper_id and self.data_manager and self.data_manager.current_paper:
                paper_id = self.data_manager.current_paper.get('id')
                
            # 获取论文数据并设置上下文
            if paper_id and self.data_manager:
                paper_data = self.data_manager.load_rag_tree(paper_id)
                if paper_data:
                    self.ai_chat.set_paper_context(paper_id, paper_data)
            
            # 设置请求参数并启动线程
            self.ai_response_thread.set_request(query, paper_id, visible_content)
            
            # 更新状态标志
            self.is_generating_response = True
            
            # 启动线程
            self.ai_response_thread.start()
            
            # 返回请求ID，以便调用者可以使用
            return request_id
        except Exception as e:
            print(f"AI响应生成失败: {str(e)}")
            self.is_generating_response = False
            self.current_request_id = None
            self.ai_response_ready.emit(f"抱歉，处理您的问题时出现错误: {str(e)}")
            return None

    def _on_ai_response_ready(self, response):
        """处理AI响应就绪事件"""
        # 更新状态标志
        self.is_generating_response = False
        
        # 发出信号通知UI
        self.ai_response_ready.emit(response)
        
        # 不再重复调用TTS - 只有在非流式响应时才使用TTS
        if not self.ai_response_thread.use_streaming:
            self._speak_response(response)
    
    def _on_ai_sentence_ready(self, sentence, emotion, scroll_info=None):
        """处理单句AI响应就绪事件"""
        # 如果没有当前请求ID，可能是已经被取消，忽略这个句子
        if not self.current_request_id:
            return
        
        # 缓存句子，并关联请求ID和情绪
        sentence_id = id(sentence)  # 使用对象id作为唯一标识
        self.pending_sentences[sentence_id] = (sentence, self.current_request_id, emotion)
        
        # 累积响应
        self.accumulated_response += sentence
        
        # 删除此行，不在AI生成时触发显示
        self.ai_sentence_ready.emit(sentence, self.current_request_id)
        
        # 处理滚动信息 - 如果有滚动信息且markdown_view被设置，则执行滚动
        if scroll_info and hasattr(self, 'markdown_view') and self.markdown_view:
            self._scroll_to_content(scroll_info)
        
        # 使用TTS朗读单句 - 传递从AI生成的实际情绪
        self._speak_response(sentence, sentence_id, emotion)

    def _speak_response(self, text, sentence_id=None, emotion="neutral"):
        """使用TTS朗读文本"""
        # 如果TTS被禁用，直接返回
        if not self.tts_enabled:
            print(f"文字转语音已禁用,跳过请求: {text[:20]}")
            return
            
        # 确保有当前请求ID
        if not self.current_request_id:
            return
        
        # 为文本添加标识，用于在TTS开始播放时匹配回来
        if sentence_id:
            # 保存文本、请求ID和情绪的映射关系，请求TTS时传递请求ID和情绪
            self.tts_manager.request_tts(text, self.current_request_id, emotion)
            # 存储映射关系（句子ID与句子内容+请求ID+情绪）
            self.pending_sentences[sentence_id] = (text, self.current_request_id, emotion)
        else:
            # 对于非流式响应，直接传递请求ID和情绪
            self.tts_manager.request_tts(text, self.current_request_id, emotion)
    
    def _on_tts_playback_started(self, text, request_id):
        """当TTS加入播放队列时调用（不再触发消息显示）"""
        # 如果请求ID不匹配当前活动请求，忽略这个播放事件
        if request_id != self.current_request_id:
            print(f"忽略过时的TTS播放：{text[:20]}... (请求ID: {request_id})")
            return
        
        # 可以在此处添加进度指示等逻辑，但不再触发消息显示
    
    def _on_tts_audio_playback_started(self, text, request_id):
        """当TTS音频实际开始播放时调用（触发消息显示）"""
        # 如果请求ID不匹配当前活动请求，忽略这个播放事件
        if request_id != self.current_request_id:
            print(f"忽略过时的TTS音频播放：{text[:20]}... (请求ID: {request_id})")
            return
            
        # 查找匹配的句子
        for sentence_id, (sentence, stored_request_id, _) in list(self.pending_sentences.items()):
            if sentence == text and stored_request_id == request_id:
                # 发出显示此句子的信号，附带请求ID
                self.ai_sentence_ready.emit(sentence, request_id)
                # 从待处理列表中移除
                self.pending_sentences.pop(sentence_id, None)
                break
    
    # 语音识别相关方法
    def toggle_voice_detection(self, active):
        """切换语音检测状态"""
        if not self.voice_input:
            return False
            
        if (active):
            return self.voice_input.start_listening()
        else:
            return self.voice_input.stop_listening()
    
    def get_voice_devices(self):
        """获取可用的语音输入设备"""
        return VoiceInput.get_input_devices()
    
    def switch_voice_device(self, device_index):
        """切换语音输入设备"""
        if not self.voice_input:
            print("语音输入系统未初始化")
            self.voice_device_switched.emit(False)
            return False
            
        # 开始切换设备并返回结果
        success = self.voice_input.switch_device(device_index)
        
        # 这里不发送信号，由voice_input的initialization_complete信号触发
        # 但需要确保正确连接这个信号到设备切换完成处理
        
        # 确保初始化完成信号连接到正确的处理方法
        if success:
            # 断开可能存在的旧连接，避免重复连接
            try:
                self.voice_input.initialization_complete.disconnect(self._on_device_switch_complete)
            except:
                pass  # 如果没有连接，忽略错误
                
            # 添加新连接，将初始化完成信号连接到设备切换完成处理
            self.voice_input.initialization_complete.connect(self._on_device_switch_complete)
        
        return success

    def _on_device_switch_complete(self, success):
        """处理设备切换完成事件"""
        # 转发信号到UI
        self.voice_device_switched.emit(success)
        
        # 断开特定连接，避免混淆普通初始化和设备切换的初始化完成信号
        try:
            self.voice_input.initialization_complete.disconnect(self._on_device_switch_complete)
        except:
            pass
            
        # 如果切换成功，也需要触发voice_ready信号
        if success:
            self.voice_ready.emit()
    
    # 语音回调转发方法
    def _on_voice_text_received(self, text):
        self.voice_text_received.emit(text)
        
    def _on_vad_started(self):
        self.vad_started.emit()
        
    def _on_vad_stopped(self):
        self.vad_stopped.emit()
        
    def _on_voice_error(self, error_message):
        self.voice_error.emit(error_message)
    
    def cleanup(self):
        """清理所有资源"""
        # 停止TTS
        if hasattr(self, 'tts_manager'):
            self.tts_manager.stop()
        
        # 停止语音识别
        if self.voice_input:
            self.voice_input.cleanup()
        
        # 停止AI响应线程
        if self.ai_response_thread and self.ai_response_thread.isRunning():
            self.ai_response_thread.requestInterruption()
            self.ai_response_thread.wait()

    def init_rag_retriever(self, base_path):
        """在后台初始化RAG检索器"""
        try:
            print(f"[INFO] 开始初始化RAG检索器: {base_path}")
            
            # 创建RAG检索器并开始后台加载
            self.retriever = RagRetriever(base_path)
            
            # 确保AI聊天模块使用相同的检索器
            if hasattr(self, 'ai_chat') and self.ai_chat:
                if self.ai_chat.retriever is not None:
                    print("[INFO] 替换AI聊天模块中的旧检索器")
                self.ai_chat.retriever = self.retriever
                
            # 连接加载完成信号以进行日志记录
            self.retriever.loading_complete.connect(self._on_retriever_loaded)
            
            return True
        except Exception as e:
            print(f"[ERROR] 初始化RAG检索器失败: {str(e)}")
            return False

    def _on_retriever_loaded(self, success):
        """处理检索器加载完成事件"""
        if success:
            print(f"[INFO] RAG检索器加载完成，共加载了 {len(self.retriever.paper_vector_paths)} 篇论文的向量库索引")
            
            # 可以添加额外验证代码
            for paper_id, path in self.retriever.paper_vector_paths.items():
                if not os.path.exists(path):
                    print(f"[WARNING] 论文 {paper_id} 的向量库路径不存在: {path}")
        else:
            print("[ERROR] RAG检索器加载失败或没有找到论文")

    def add_paper_vector_store(self, paper_id, vector_store_path):
        """添加新论文的向量库
        
        在处理完新论文后调用此方法
        
        Args:
            paper_id: 论文ID
            vector_store_path: 向量库路径
            
        Returns:
            bool: 成功返回True
        """
        if hasattr(self, 'retriever'):
            return self.retriever.add_paper(paper_id, vector_store_path)
        return False

    def _scroll_to_content(self, scroll_info):
        """根据滚动信息滚动到对应内容"""
        if not scroll_info:
            return
            
        # 获取当前语言
        current_lang = self.markdown_view.get_current_language()
        
        # 根据当前语言选择内容
        content = scroll_info['zh_content'] if current_lang == 'zh' else scroll_info['en_content']
        node_type = scroll_info.get('node_type', 'text')
        is_title = scroll_info.get('is_title', False)
        
        # 如果内容为空，尝试使用另一种语言的内容
        if not content:
            content = scroll_info['en_content'] if current_lang == 'zh' else scroll_info['zh_content']
        
        # 执行滚动
        if content:
            # 根据节点类型确定滚动类型
            if is_title:
                self.markdown_view._scroll_to_matching_content(content, 'title')
            else:
                self.markdown_view._scroll_to_matching_content(content, 'text')

    def set_tts_enabled(self, enabled: bool):
        """设置TTS是否启用
        
        Args:
            enabled: True表示启用TTS，False表示禁用TTS
        """
        self.tts_enabled = enabled
        if not enabled:
            # 如果禁用TTS，停止当前所有播放
            self.tts_manager.stop_playing()

    def is_tts_enabled(self) -> bool:
        """获取TTS是否启用
        
        Returns:
            bool: True表示TTS已启用，False表示已禁用
        """
        return self.tts_enabled