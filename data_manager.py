import os
import json
import shutil
from PyQt6.QtCore import QObject, pyqtSignal
from pipeline import Pipeline
from threads import ProcessingThread

class DataManager(QObject):
    """
    后端数据管理类
    
    负责所有数据的加载、处理和管理，作为前端UI和数据之间的桥梁
    """
    # 定义信号
    papers_loaded = pyqtSignal(list)                         # 论文列表加载完成信号
    paper_content_loaded = pyqtSignal(dict, str, str)        # 论文内容加载完成信号(paper_data, zh_content, en_content)
    loading_error = pyqtSignal(str)                          # 加载错误信号
    message = pyqtSignal(str)                                # 一般消息信号
    processing_started = pyqtSignal(str)                     # 开始处理论文信号
    processing_progress = pyqtSignal(str, str, float, int)   # (文件名, 阶段, 进度, 剩余数量)
    processing_finished = pyqtSignal(str)                    # 处理完成的论文ID
    processing_error = pyqtSignal(str, str)                  # (论文ID, 错误信息)
    queue_updated = pyqtSignal(list)                         # 队列更新信号
    
    def __init__(self, base_dir=None):
        """初始化数据管理器"""
        super().__init__()
        
        # 初始化目录结构
        self._init_directories(base_dir)
        
        # 初始化数据状态
        self.papers_index = []
        self.current_paper = None
        
        # 初始化处理队列和状态
        self._init_processing_queue()
        
        # 初始化处理管线
        self._init_pipeline()
    
    # ========== 初始化相关方法 ==========
    
    def _init_directories(self, base_dir):
        """初始化基础目录结构"""
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.output_dir = os.path.join(self.base_dir, "output")
        self.data_dir = os.path.join(self.base_dir, "data")
        
        # 确保目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.data_dir, exist_ok=True)
    
    def _init_processing_queue(self):
        """初始化处理队列和状态"""
        self.processing_queue = []    # 待处理文件队列
        self.is_processing = False    # 是否正在处理
        self.is_paused = True         # 初始状态为暂停
        self.current_thread = None    # 当前处理线程
    
    def _init_pipeline(self):
        """初始化处理管线"""
        self.pipeline = Pipeline()
        self.pipeline.progress_updated.connect(self.on_pipeline_progress)
    
    # ========== 论文索引加载管理 ==========
    
    def load_papers_index(self):
        """加载论文索引数据"""
        try:
            index_path = os.path.join(self.output_dir, "papers_index.json")
            if os.path.exists(index_path):
                with open(index_path, 'r', encoding='utf-8') as f:
                    self.papers_index = json.load(f)
                self.message.emit(f"成功从 {index_path} 加载论文索引")
                self.papers_loaded.emit(self.papers_index)
            else:
                self.message.emit(f"索引文件不存在: {index_path}")
        except Exception as e:
            self.loading_error.emit(f"加载论文索引失败: {str(e)}")
    
    # ========== 论文内容加载 ==========
    
    def load_paper_content(self, paper_id):
        """
        加载指定论文的内容
        
        Args:
            paper_id: 论文ID
        
        Returns:
            tuple: (paper, zh_content, en_content)
        """
        # 查找指定ID的论文
        paper = next((p for p in self.papers_index if p["id"] == paper_id), None)
        
        if not paper:
            self.loading_error.emit(f"未找到ID为{paper_id}的论文")
            return None, "", ""
        
        self.current_paper = paper
        self.message.emit(f"尝试加载论文: {paper.get('translated_title', '')} ({paper_id})")
        
        # 获取路径信息
        paths = paper.get('paths', {})
        en_path = paths.get('article_en', '')
        zh_path = paths.get('article_zh', '')
        en_full_path = os.path.join(self.output_dir, en_path)
        zh_full_path = os.path.join(self.output_dir, zh_path)
        
        # 加载中文和英文内容
        zh_content = self._load_document_content(
            zh_full_path, 
            f"# {paper.get('translated_title', '')}", 
            is_chinese=True
        )
        
        en_content = self._load_document_content(
            en_full_path, 
            f"# {paper.get('title', '')}", 
            is_chinese=False
        )
        
        # 验证图片路径
        self._verify_images_path(paper)
        
        # 发送加载完成信号
        self.paper_content_loaded.emit(paper, zh_content, en_content)
        return paper, zh_content, en_content
    
    def _load_document_content(self, file_path, default_title, is_chinese=True):
        """
        加载文档内容
        
        Args:
            file_path: 文档路径
            default_title: 默认标题
            is_chinese: 是否中文文档
        
        Returns:
            str: 文档内容
        """
        lang_desc = "中文" if is_chinese else "英文"
        
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception as e:
                self.loading_error.emit(f"加载{lang_desc}文档失败: {str(e)}")
                return f"{default_title}\n\n加载{lang_desc}文档时出错: {str(e)}"
        else:
            self.message.emit(f"{lang_desc}文档不存在: {file_path}")
            return f"{default_title}\n\n{lang_desc}文档不存在或无法访问。\n路径: {file_path}"
    
    def _verify_images_path(self, paper):
        """验证论文图片路径是否存在"""
        images_path = paper.get('paths', {}).get('images', '')
        if images_path:
            full_images_path = os.path.join(self.output_dir, images_path)
            if not os.path.exists(full_images_path):
                self.message.emit(f"警告: 图片目录不存在: {full_images_path}")
    
    # ========== RAG树相关 ==========
    
    def load_rag_tree(self, paper_id):
        """
        加载指定论文的RAG树结构
        
        Args:
            paper_id: 论文ID
            
        Returns:
            dict: RAG树结构，如果加载失败则返回None
        """
        # 查找指定ID的论文
        paper = next((p for p in self.papers_index if p["id"] == paper_id), None)
        
        if not paper:
            self.loading_error.emit(f"未找到ID为{paper_id}的论文")
            return None
        
        # 获取RAG树路径
        rag_tree_path = paper.get('paths', {}).get('rag_tree', '')
        
        if not rag_tree_path:
            self.message.emit(f"论文 {paper_id} 没有RAG树路径")
            return None
        
        # 构建基于当前应用目录的绝对路径
        rag_tree_full_path = os.path.join(self.output_dir, rag_tree_path)
        
        self.message.emit(f"尝试加载RAG树: {rag_tree_full_path}")
        
        # 加载RAG树
        if os.path.exists(rag_tree_full_path):
            try:
                with open(rag_tree_full_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.loading_error.emit(f"加载RAG树失败: {str(e)}")
                return None
        else:
            self.message.emit(f"RAG树文件不存在: {rag_tree_full_path}")
            return None

    def find_matching_content(self, text_fragment, lang="zh", element_type="text"):
        """
        在当前论文的RAG树中查找最匹配的内容
        
        Args:
            text_fragment: 要匹配的文本片段
            lang: 语言代码，'zh'表示中文，'en'表示英文
            element_type: 元素类型，'title', 'text' 或 'table'
                'text': 匹配标题或文本描述
                'table': 匹配表格内容
                'title': 匹配章节标题
            
        Returns:
            tuple: (对应的另一种语言的内容, 匹配到的元素类型)
        """
        if not self.current_paper:
            self.message.emit("没有加载论文，无法查找匹配内容")
            return None, None
        
        # 加载RAG树
        rag_tree = self.load_rag_tree(self.current_paper['id'])
        if not rag_tree:
            self.message.emit("无法加载RAG树，无法查找匹配内容")
            return None, None
        
        # 特殊处理：摘要匹配
        if element_type == 'title' and ("abstract" in text_fragment.lower() or "摘要" in text_fragment):
            return "abstract" if lang == "zh" else "摘要", "title"
            
        # 根据元素类型选择搜索策略
        if element_type == 'title':
            return self._search_title_match(rag_tree, text_fragment, lang)
        else:
            return self._search_content_match(rag_tree, text_fragment, lang, element_type)
    
    def _search_title_match(self, rag_tree, text_fragment, lang):
        """在RAG树中搜索标题匹配"""
        source_field, target_field = self._get_field_names("document_title", lang)
        
        # 检查文档标题
        if source_field in rag_tree and target_field in rag_tree:
            if rag_tree[source_field] == text_fragment:
                return rag_tree[target_field], 'title'
        
        # 递归搜索章节标题
        def search_title_in_sections(sections):
            for section in sections:
                if source_field in section and section[source_field] == text_fragment:
                    return section[target_field], 'title'
                    
                # 递归搜索子章节
                if "children" in section and section["children"]:
                    result, type_found = search_title_in_sections(section["children"])
                    if result:
                        return result, type_found
            return None, None
                
        # 开始搜索章节标题
        if "sections" in rag_tree:
            return search_title_in_sections(rag_tree["sections"])
        
        return None, None
    
    def _search_content_match(self, rag_tree, text_fragment, lang, element_type):
        """在RAG树中搜索内容匹配"""
        # 特殊处理：首先检查摘要内容
        if "abstract" in rag_tree:
            source_field, target_field = self._get_field_names("text", lang)
            
            if source_field in rag_tree["abstract"] and target_field in rag_tree["abstract"]:
                abstract_content = rag_tree["abstract"][source_field]
                if self._is_text_match(abstract_content, text_fragment):
                    return rag_tree["abstract"][target_field], "text"

        # 递归搜索章节内容
        def search_in_sections(sections):
            for section in sections:
                # 搜索当前章节的内容
                if "content" in section:
                    for node in section["content"]:
                        node_type = node.get("type", "")
                        
                        # 跳过公式节点
                        if node_type == "formula":
                            continue
                        
                        # 特殊处理表格节点
                        if node_type == "table":
                            result, type_found = self._match_table_node(node, text_fragment, lang, element_type)
                            if result:
                                return result, type_found
                        # 处理普通文本节点
                        else:
                            source_field, target_field = self._get_field_names(node_type, lang)
                            if not source_field or source_field not in node:
                                continue
                                
                            content = node[source_field]
                                    
                            # 使用改进的匹配
                            if self._is_text_match(content, text_fragment):
                                return node.get(target_field), "text"
                
                # 递归搜索子章节
                if "children" in section and section["children"]:
                    result, type_found = search_in_sections(section["children"])
                    if result:
                        return result, type_found
            
            return None, None
        
        # 开始搜索
        if "sections" in rag_tree:
            return search_in_sections(rag_tree["sections"])
        
        return None, None
    
    def _match_table_node(self, node, text_fragment, lang, element_type):
        """匹配表格节点"""
        if element_type == "text":
            # 当寻找文本时，匹配表格的标题/说明
            source_field, target_field = self._get_field_names("table", lang)
            if source_field in node:
                caption = node[source_field]
                if self._is_text_match(caption, text_fragment):
                    return node.get(target_field), "text"
        elif element_type == "table":
            # 当寻找表格时，匹配表格内容
            content_field = "content"
            if content_field in node:
                table_content = node[content_field]
                cleaned_content = self._clean_text(table_content)
                if self._is_text_match(cleaned_content, text_fragment):
                    return node.get(content_field), "table"
        return None, None
    
    def _get_field_names(self, node_type, lang):
        """获取字段名称"""
        if node_type == "text":
            return ("translated_content" if lang == "zh" else "content", 
                    "content" if lang == "zh" else "translated_content")
        elif node_type in ["figure", "table"]:
            return ("translated_caption" if lang == "zh" else "caption", 
                    "caption" if lang == "zh" else "translated_caption")
        elif node_type == "formula":
            return "content", "content"
        elif node_type in ["section_title", "document_title"]:
            return ("translated_title" if lang == "zh" else "title", 
                    "title" if lang == "zh" else "translated_title")
        return None, None
    
    def _clean_text(self, text):
        """清理HTML标签和LaTeX公式"""
        if not text:
            return ""
        import re
        
        # 先移除HTML标签
        text = re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*(\s+[^>]*)?>', ' ', text)
        
        # 移除行间公式 ($$...$$)
        text = re.sub(r'\$\$[^$]*\$\$', ' ', text)
        
        # 移除行内公式 ($...$)
        text = re.sub(r'\$[^$]*\$', ' ', text)
        
        # 移除其他可能的LaTeX表示 (\(...\) 和 \[...\])
        text = re.sub(r'\\[\(\[][^\\]*\\[\)\]]', ' ', text)
        
        # 清理多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        return text
    
    def _is_text_match(self, s1, s2):
        """检查两个文本是否互相包含（子串关系）"""
        if not s1 or not s2:
            return False
        
        # 清理并标准化两个文本
        def normalize_text(text):
            # 先清理LaTeX和HTML
            cleaned = self._clean_text(text)
            import re
            # 保留中文、英文字母和数字，移除所有其他字符
            normalized = re.sub(r'[^\u4e00-\u9fff\w\d]', '', cleaned)
            return normalized.lower()  # 转为小写以忽略大小写差异
        
        # 获取标准化后的全文
        norm_s1 = normalize_text(s1)
        norm_s2 = normalize_text(s2)
        
        # 检查是否存在子串关系（双向检查）
        return norm_s1 in norm_s2 or norm_s2 in norm_s1
    
    # ========== 论文处理队列管理 ==========
    
    def initialize_processing_system(self):
        """初始化处理系统，检查未处理文件并构建队列"""
        # 加载现有索引
        self.load_papers_index()
        
        # 初始化处理管线（如果尚未初始化）
        if self.pipeline is None:
            self._init_pipeline()
        
        # 扫描数据目录中的PDF文件
        self.scan_for_unprocessed_files()
    
    def scan_for_unprocessed_files(self):
        """扫描数据目录，查找未处理或处理不完整的PDF文件"""
        # 清空现有队列
        self.processing_queue = []
        
        # 获取已处理论文的ID列表
        processed_ids = {paper['id'] for paper in self.papers_index}
        
        # 扫描数据目录中的PDF文件
        pdf_files = [f for f in os.listdir(self.data_dir) if f.lower().endswith('.pdf')]
        
        # 对于每个PDF文件，检查是否已经处理
        for pdf_file in pdf_files:
            paper_id = os.path.splitext(pdf_file)[0]  # 不包含扩展名的文件名作为ID
            
            # 检查是否已经在索引中并且处理完整
            if paper_id not in processed_ids:
                # 新文件，添加到队列
                self.processing_queue.append({
                    'id': paper_id,
                    'path': os.path.join(self.data_dir, pdf_file),
                    'status': 'pending',
                    'missing_steps': ['all'],  # 全部步骤都缺失
                })
            else:
                # 检查是否所有必要文件都存在
                paper_info = next((p for p in self.papers_index if p['id'] == paper_id), None)
                missing_paths = self._check_missing_paths(paper_info)
                
                if missing_paths:
                    # 处理不完整，添加到队列
                    self.processing_queue.append({
                        'id': paper_id,
                        'path': os.path.join(self.data_dir, pdf_file),
                        'status': 'incomplete',
                        'missing_steps': missing_paths,
                    })
        
        # 按缺失步骤数排序（缺失少的在前）
        self.processing_queue.sort(key=lambda x: len(x.get('missing_steps', [])))
        
        # 发射队列更新信号
        self.queue_updated.emit(self.processing_queue)
        
        self.message.emit(f"扫描完成，发现 {len(self.processing_queue)} 个待处理文件")
    
    def _check_missing_paths(self, paper_info):
        """检查论文是否缺少关键文件，返回缺失的文件类型列表"""
        if not paper_info:
            return ['all']
        
        missing = []
        paths = paper_info.get('paths', {})
        
        # 检查关键文件
        key_files = {
            'article_en': '英文文章',
            'article_zh': '中文文章',
            'rag_tree': 'RAG树结构'
        }
        
        for key, desc in key_files.items():
            if key not in paths or not os.path.exists(os.path.join(self.output_dir, paths[key])):
                missing.append(key)
        
        return missing
    
    def upload_file(self, file_path):
        """上传文件到数据目录并添加到处理队列"""
        try:
            # 检查文件是否存在
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"文件不存在: {file_path}")
            
            # 提取文件名作为论文ID
            file_name = os.path.basename(file_path)
            paper_id = os.path.splitext(file_name)[0]
            
            # 目标路径
            target_path = os.path.join(self.data_dir, file_name)
            
            # 复制文件到数据目录（如果需要）
            self._copy_file_to_data_dir(file_path, target_path)
            
            # 更新处理队列
            self._update_processing_queue(paper_id, target_path)
            
            # 如果不是暂停状态，开始处理
            if not self.is_paused:
                self.process_next_in_queue()
            
            return True
        except Exception as e:
            self.loading_error.emit(f"上传文件失败: {str(e)}")
            return False
    
    def _copy_file_to_data_dir(self, file_path, target_path):
        """复制文件到数据目录"""
        # 规范化路径进行比较，检查是否是同一文件
        try:
            is_same_file = os.path.samefile(file_path, target_path)
        except:
            # 如果samefile失败（例如文件不存在），则使用normpath进行比较
            is_same_file = os.path.normpath(file_path) == os.path.normpath(target_path)
        
        # 如果不是同一文件，才进行复制
        if not is_same_file:
            try:
                shutil.copy2(file_path, target_path)
                self.message.emit(f"文件已复制到数据目录: {target_path}")
            except Exception as e:
                self.loading_error.emit(f"复制文件时出错: {str(e)}")
                # 继续执行，假设文件已存在或其他原因可以忽略
        else:
            self.message.emit(f"文件已在数据目录中: {target_path}")
    
    def _update_processing_queue(self, paper_id, file_path):
        """更新处理队列"""
        # 检查是否已在队列中
        existing_item = next((item for item in self.processing_queue if item['id'] == paper_id), None)
        
        if existing_item:
            # 已在队列中，更新状态并移至队首
            existing_item['status'] = 'pending'
            existing_item['path'] = file_path
            existing_item['priority'] = 1  # 确保高优先级
            
            # 将项目移到队列开头
            self.processing_queue.remove(existing_item)
            self.processing_queue.insert(0, existing_item)
        else:
            # 添加到队列开头（而不是末尾）
            self.processing_queue.insert(0, {
                'id': paper_id,
                'path': file_path,
                'status': 'pending',
                'missing_steps': ['all'],
                'priority': 1  # 添加一个高优先级标记
            })
        
        # 更新队列
        self.queue_updated.emit(self.processing_queue)
    
    def process_next_in_queue(self):
        """处理队列中的下一个文件"""
        if self.is_paused or self.is_processing or not self.processing_queue:
            return False
        
        # 获取队列中第一个待处理项
        next_item = self.processing_queue[0]
        
        # 标记为正在处理
        self.is_processing = True
        next_item['status'] = 'processing'
        
        # 更新队列状态
        self.queue_updated.emit(self.processing_queue)
        
        # 发出开始处理信号
        self.processing_started.emit(next_item['id'])
        
        # 创建并启动处理线程
        self.current_thread = ProcessingThread(
            self.pipeline, next_item['path'], self.output_dir
        )
        self.current_thread.processing_finished.connect(self.on_processing_finished)
        self.current_thread.processing_error.connect(self.on_processing_error)
        self.current_thread.start()
        
        return True
    
    # ========== 处理线程回调 ==========
    
    def on_thread_progress(self, file_name, stage, progress, remaining):
        """处理线程进度更新回调"""
        self.processing_progress.emit(file_name, stage, progress, remaining)
    
    def on_pipeline_progress(self, stage_info):
        """管线进度更新回调"""
        # 构建当前处理的文件名
        if self.is_processing and self.processing_queue:
            file_name = os.path.basename(self.processing_queue[0]['path'])
            stage = stage_info.get('stage_name', '未知阶段')
            progress = stage_info.get('progress', 0)
            remaining = len(self.processing_queue) - 1
            
            # 发送进度更新信号
            self.processing_progress.emit(file_name, stage, progress, remaining)
    
    def on_processing_finished(self, paper_id):
        """处理完成回调"""
        self.message.emit(f"论文处理完成: {paper_id}")
        
        # 标记处理完成
        self.is_processing = False
        
        # 从队列中移除已处理项
        if self.processing_queue:
            self.processing_queue.pop(0)
        
        # 发送处理完成信号
        self.processing_finished.emit(paper_id)
        
        # 添加向量库到RAG检索器
        self._add_paper_vector_store(paper_id)
        
        # 更新队列状态
        self.queue_updated.emit(self.processing_queue)
        
        # 重新加载论文索引
        self.load_papers_index()
        
        # 继续处理下一个（如果未暂停）
        if not self.is_paused:
            self.process_next_in_queue()

    def _add_paper_vector_store(self, paper_id):
        """将处理完成的论文向量库添加到RAG检索器"""
        try:
            # 获取论文数据
            paper = next((p for p in self.papers_index if p["id"] == paper_id), None)
            if not paper:
                self.message.emit(f"[WARNING] 未找到ID为{paper_id}的论文，无法添加向量库")
                return False
                
            # 获取向量库路径
            vector_store_path = paper.get('paths', {}).get('rag_vector_store')
            if not vector_store_path:
                self.message.emit(f"[WARNING] 论文{paper_id}没有向量库路径")
                return False
                
            # 构建完整路径
            full_path = os.path.join(self.output_dir, vector_store_path)
            
            # 验证路径是否存在
            if not os.path.exists(full_path):
                self.message.emit(f"[WARNING] 论文{paper_id}的向量库路径不存在: {full_path}")
                return False
            
            # 通过AI管理器添加向量库
            if hasattr(self, 'ai_manager') and self.ai_manager:
                success = self.ai_manager.add_paper_vector_store(paper_id, full_path)
                if success:
                    self.message.emit(f"已添加论文 {paper_id} 的向量库到检索系统")
                else:
                    self.message.emit(f"[WARNING] 添加论文 {paper_id} 的向量库失败")
                return success
            else:
                self.message.emit(f"[WARNING] AI管理器未初始化，无法添加向量库")
                return False
                
        except Exception as e:
            self.message.emit(f"[ERROR] 添加向量库失败: {str(e)}")
            return False
    
    def on_processing_error(self, paper_id, error_msg):
        """处理错误回调"""
        # 由于我们可能通过强制终止线程导致错误，需要检查处理状态
        if not self.is_processing:
            # 线程已被手动停止，无需报告错误
            return
            
        self.loading_error.emit(f"处理论文 {paper_id} 时出错: {error_msg}")
        
        # 标记处理结束
        self.is_processing = False
        
        # 从队列中移除错误项
        if self.processing_queue and len(self.processing_queue) > 0:
            self.processing_queue[0]['status'] = 'error'
            self.processing_queue[0]['error_msg'] = error_msg
            self.processing_queue.pop(0)
        
        # 更新队列状态
        self.queue_updated.emit(self.processing_queue)
        
        # 继续处理下一个（如果未暂停）
        if not self.is_paused:
            self.process_next_in_queue()
    
    # ========== 队列控制 ==========
    
    def pause_processing(self):
        """暂停处理队列"""
        self.is_paused = True
        self.message.emit("处理队列已暂停")
        
        # 立即停止当前正在运行的线程
        if self.current_thread and self.current_thread.isRunning():
            self.current_thread.stop()  # 立即终止线程
            self.is_processing = False  # 重置处理状态
            
            # 如果队列不为空，将当前任务重置为待处理状态
            if self.processing_queue and len(self.processing_queue) > 0:
                current_item = self.processing_queue[0]
                current_item['status'] = 'pending'
                self.message.emit(f"已停止处理论文: {current_item['id']}")
            
            # 更新队列状态
            self.queue_updated.emit(self.processing_queue)
    
    def resume_processing(self):
        """继续处理队列"""
        self.is_paused = False
        self.message.emit("处理队列已继续")
        
        # 如果没有正在进行的处理，尝试处理下一个
        if not self.is_processing:
            self.process_next_in_queue()
    
    def set_ai_manager(self, ai_manager):
        """设置AI管理器引用"""
        self.ai_manager = ai_manager
        
    def toggle_md_processor(self, use_slides_processor):
        """
        切换Markdown处理器类型
        Args:
            use_slides_processor: True使用幻灯片处理器，False使用标准处理器
            
        Returns:
            bool: 切换后当前使用的是否为幻灯片处理器
        """
        try:
            # 调用管线的切换方法
            if hasattr(self, 'pipeline'):
                result = self.pipeline.toggle_md_processor(use_slides_processor)
                return result
            return False
        except Exception as e:
            self.loading_error.emit(f"切换Markdown处理器失败: {str(e)}")
            return False