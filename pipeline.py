from pathlib import Path
import json
import logging
from typing import Optional, Dict, List, Union
from processor.pdf_processor import PDFProcessor
from processor.md_processor import MarkdownProcessor
from processor.json_processor import JsonProcessor
from processor.tiling_processor import TilingProcessor
from processor.translate_processor import TranslateProcessor
from processor.md_restore_processor import RestoreProcessor
from processor.extra_info_processor import ExtraInfoProcessor
from processor.rag_processor import RagProcessor
from processor.md_processor_slides import MarkdownProcessorSlides
from PyQt6.QtCore import QObject, pyqtSignal

# 配置日志
logger = logging.getLogger(__name__)

class Pipeline(QObject):
    """学术论文处理管线"""
    # 添加进度更新信号
    progress_updated = pyqtSignal(dict)  # 发送stage_info字典
    
    def __init__(self, stages: Optional[List[str]] = None):
        """
        初始化处理管线
        
        Args:
            stages: 需要运行的处理阶段列表
                   可选值: ['pdf2md', 'md2json', 'json_process', 
                          'tiling', 'translate', 'md_restore', 'extra_info', 'rag']
        """
        super().__init__()  # 调用QObject初始化
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # 定义阶段标识符和对应的处理函数
        self.stage_identifiers = {
            'pdf2md': '',
            'md2json': '_structured',
            'json_process': '_processed',
            'tiling': '_tiled',
            'translate': '_translated',
            'md_restore': '_restored',
            'extra_info': '_extra_info',
            'rag': '_rag'
        }
        
        self.available_stages = {
            'pdf2md': self._stage_pdf_to_md,
            'md2json': self._stage_md_to_json,
            'json_process': self._stage_json_process,
            'tiling': self._stage_tiling,
            'translate': self._stage_translate,
            'md_restore': self._stage_md_restore,
            'extra_info': self._stage_extra_info,
            'rag': self._stage_rag
        }
        self.stages = stages or list(self.available_stages.keys())
        self.logger.debug("初始化处理阶段: %s", self.stages)
        
        # 初始化处理器
        self.pdf_processor = PDFProcessor()
        self.md_processor = MarkdownProcessor()
        self.md_processor_original = MarkdownProcessor()
        self.md_processor_slides = MarkdownProcessorSlides()
        self.json_processor = JsonProcessor()
        self.tiling_processor = TilingProcessor()
        self.translate_processor = TranslateProcessor()
        self.restore_processor = RestoreProcessor()
        self.extra_info_processor = ExtraInfoProcessor()
        self.rag_processor = RagProcessor()
        
        # 论文处理状态
        self.paper_info = {
            'paper_id': None,     # 论文ID（基于PDF文件名）
            'output_dir': None    # 输出目录
        }

        # 添加跟踪当前处理阶段的属性
        self._current_stage = None

    def _change_md_processor(self, processor: MarkdownProcessor):
        print("on _change_md_processor")
        self.md_processor = processor
        
    def toggle_md_processor(self, use_slides_processor: bool):
        """
        切换Markdown处理器
        
        Args:
            use_slides_processor: True使用幻灯片处理器，False使用标准处理器
        
        Returns:
            bool: 当前使用的是否为幻灯片处理器
        """
        print("signal received 切换Markdown处理器")
        try:
            if use_slides_processor:
                self.logger.info("切换到幻灯片处理器")
                self.md_processor = self.md_processor_slides
            else:
                self.logger.info("切换到标准处理器")
                self.md_processor = self.md_processor_original
            return self.is_using_slides_processor()
        except Exception as e:
            self.logger.error(f"切换Markdown处理器失败: {str(e)}")
            return self.is_using_slides_processor()
    
    def is_using_slides_processor(self) -> bool:
        """
        检查当前使用的处理器是否为幻灯片处理器
        
        Returns:
            bool: True表示使用幻灯片处理器，False表示使用标准处理器
        """
        return isinstance(self.md_processor, MarkdownProcessorSlides)

    def _get_stage_output_path(self, stage: str, paper_dir: Path, paper_name: str) -> Path:
        """
        获取特定阶段的输出文件路径
        
        Args:
            stage: 处理阶段名称
            paper_dir: 论文输出目录
            paper_name: 论文名称
            
        Returns:
            Path: 输出文件路径
        """
        identifier = self.stage_identifiers.get(stage, '')
        if stage == 'pdf2md':
            return paper_dir / f"{paper_name}{identifier}.md"
        elif stage == 'md_restore':
            # 对于restore阶段，返回一个包含英文和中文输出路径的字典
            return {
                'en': paper_dir / f"final_{paper_name}_en.md",
                'zh': paper_dir / f"final_{paper_name}_zh.md"
            }
        elif stage == 'rag':
            # 对于RAG阶段，返回一个包含md、tree_json和vector_store输出路径的字典
            return {
                'md': paper_dir / f"final_{paper_name}_rag.md",
                'tree_json': paper_dir / f"final_{paper_name}_rag_tree.json",
                'vector_store': paper_dir / "vectors"
            }
        else:
            return paper_dir / f"{paper_name}{identifier}.json"
        
    def get_current_stage(self) -> Dict[str, any]:
        """
        获取当前处理阶段的信息
        
        Returns:
            Dict: 包含当前阶段信息的字典，格式为:
                {
                    'stage': 当前阶段名称,
                    'stage_name': 当前阶段显示名称,
                    'index': 当前阶段在所有阶段中的索引位置,
                    'total': 总阶段数,
                    'progress': 完成百分比,
                    'stage_progress': 当前阶段内部进度
                }
        """
        # 阶段名称的友好显示映射
        stage_names = {
            'pdf2md': 'PDF转Markdown',
            'md2json': 'Markdown转JSON',
            'json_process': 'JSON处理',
            'tiling': '分段处理',
            'translate': '内容翻译',
            'md_restore': '生成Markdown文档',
            'extra_info': '提取额外信息',
            'rag': 'RAG处理'
        }
        
        if self._current_stage is None:
            return {
                'stage': None,
                'stage_name': '未开始',
                'index': 0,
                'total': len(self.stages),
                'progress': 0,
                'stage_progress': 0
            }
        
        current_index = self.stages.index(self._current_stage) if self._current_stage in self.stages else -1
        
        result = {
            'stage': self._current_stage,
            'stage_name': stage_names.get(self._current_stage, self._current_stage),
            'index': current_index + 1,
            'total': len(self.stages),
            'progress': int((current_index + 1) / len(self.stages) * 100) if current_index >= 0 else 0,
            'stage_progress': 0  # 可以根据需要添加阶段内进度
        }
        
        # 发送进度更新信号
        self.progress_updated.emit(result)
        
        return result
    
    def process(self, pdf_path: str, output_dir: Optional[str] = None) -> Dict[str, Union[Path, Dict[str, Path]]]:
        """
        处理论文的主函数
        
        Args:
            pdf_path: PDF文件路径
            output_dir: 输出目录，默认为PDF所在目录

        Returns:
            Dict[str, Path]: 各阶段输出文件的路径字典
        """
        try:
            # 规范化路径
            pdf_path = Path(pdf_path)
            if not pdf_path.exists():
                raise FileNotFoundError(f"PDF文件不存在: {pdf_path}")

            # 设置基础输出目录
            base_output_dir = Path(output_dir) if output_dir else pdf_path.parent
            base_output_dir.mkdir(exist_ok=True, parents=True)
            
            # 初始化论文信息
            self.paper_info['paper_id'] = pdf_path.stem
            
            # 创建输出目录
            paper_output_dir = base_output_dir / self.paper_info['paper_id']
            paper_output_dir.mkdir(exist_ok=True)
            self.paper_info['output_dir'] = paper_output_dir
            
            # 存储各阶段的输出路径
            output_paths = {}
            
            # 运行选定的处理阶段
            for stage in self.stages:
                if stage not in self.available_stages:
                    self.logger.warning(f"未知的处理阶段: {stage}")
                    continue

                # 设置当前阶段
                self._current_stage = stage
                self.progress_updated.emit(self.get_current_stage())
                self.logger.info(f"开始运行阶段: {stage}")
   
                # 获取该阶段的预期输出路径
                expected_output = self._get_stage_output_path(stage, paper_output_dir, self.paper_info['paper_id'])
                
                # 检查输出文件是否已存在
                if stage in ['md_restore', 'rag']:
                    # 对于有多个输出文件的阶段，检查所有文件是否都已存在
                    files_exist = True
                    for _, path in expected_output.items():
                        if not path.exists():
                            files_exist = False
                            break
                            
                    if files_exist:
                        self.logger.info(f"阶段 {stage} 的输出文件已存在，跳过处理: {expected_output}")
                        output_paths[stage] = expected_output
                        continue
                else:
                    if isinstance(expected_output, Path) and expected_output.exists():
                        self.logger.info(f"阶段 {stage} 的输出文件已存在，跳过处理: {expected_output}")
                        output_paths[stage] = expected_output
                        continue
                
                # 执行处理阶段
                self.logger.info(f"开始运行阶段: {stage}")
                logger.info(f"\n参数: pdf {pdf_path}\n paper_output_dir {paper_output_dir}\n paper_info {self.paper_info['paper_id']}\n output_paths {output_paths}")
                stage_output = self.available_stages[stage](
                    pdf_path, paper_output_dir, self.paper_info['paper_id'], output_paths
                )
                logger.info(f"阶段{stage},输出: {stage_output}")
                output_paths[stage] = stage_output
                self.logger.info(f"阶段 {stage} 完成")

            # 处理完成后
            self._current_stage = None
            
            # 如果RAG或MD_RESTORE阶段已完成，更新全局索引
            final_paths = {}
            
            logger.info(f"output_paths: {output_paths}")
            
            # 收集最终文件路径
            if 'md_restore' in output_paths:
                restore_paths = output_paths['md_restore']
                final_paths.update({
                    'article_en': restore_paths['en'],
                    'article_zh': restore_paths['zh']
                })
                
            if 'rag' in output_paths:
                rag_paths = output_paths['rag']
                final_paths.update({
                    'rag_md': rag_paths['md'],
                    'rag_tree': rag_paths['tree_json'],
                    'rag_vector_store': rag_paths['vector_store']
                })
                
            # 检查图像文件夹
            images_dir = paper_output_dir / "images"
            if images_dir.exists() and images_dir.is_dir():
                final_paths['images'] = images_dir
                
            # 如果有最终文件，更新索引
            if final_paths:
                self._update_global_index(base_output_dir, final_paths)
                output_paths['final'] = final_paths
            
            return output_paths
            
        except Exception as e:
            self.logger.error(f"处理过程出错: {str(e)}", exc_info=True)
            raise

    def _update_global_index(self, base_output_dir: Path, final_paths: Dict) -> None:
        """
        更新全局论文索引
        
        Args:
            base_output_dir: 基础输出目录
            final_paths: 最终文件路径字典
        """
        index_path = base_output_dir / "papers_index.json"
        
        # 读取现有索引（如果存在）
        papers_index = []
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    papers_index = json.load(f)
            except json.JSONDecodeError:
                self.logger.warning(f"索引文件损坏，将创建新索引: {index_path}")
                papers_index = []
        
        # 构建论文条目
        # 将路径字符串化，保存相对路径以避免跨机器使用时的问题
        path_dict = {}
        for key, path in final_paths.items():
            if path:
                # 将路径转换为相对于基础输出目录的相对路径
                try:
                    rel_path = path.relative_to(base_output_dir)
                    path_dict[key] = str(rel_path)
                except ValueError:
                    # 如果无法获取相对路径，则使用绝对路径
                    path_dict[key] = str(path)
        
        # 从 rag_tree.json 提取 title 和 translated_title
        title = ""
        translated_title = ""
        if 'rag_tree' in final_paths and Path(final_paths['rag_tree']).exists():
            try:
                with open(final_paths['rag_tree'], 'r', encoding='utf-8') as f:
                    tree_data = json.load(f)
                    title = tree_data.get('title', '')
                    translated_title = tree_data.get('translated_title', '')
                    self.logger.info(f"从RAG树中提取标题: {title}, 翻译标题: {translated_title}")
            except Exception as e:
                self.logger.error(f"从RAG树中提取标题时出错: {str(e)}")
        
        paper_entry = {
            'id': self.paper_info['paper_id'],
            'title': title,
            'translated_title': translated_title,
            'paths': path_dict
        }
        
        # 查找现有条目
        existing_index = -1
        for i, entry in enumerate(papers_index):
            if entry.get('id') == paper_entry['id']:
                existing_index = i
                break
        
        # 更新或添加条目
        if existing_index >= 0:
            papers_index[existing_index] = paper_entry
        else:
            papers_index.append(paper_entry)
        
        # 保存更新后的索引
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(papers_index, f, ensure_ascii=False, indent=2)
        
        self.logger.info(f"全局索引更新完成: {index_path}")

    def _stage_pdf_to_md(self, pdf_path: Path, paper_dir: Path, 
                        paper_name: str, output_paths: dict) -> Path:
        """PDF转Markdown阶段"""
        self.logger.info(f"开始将PDF转换为Markdown: {pdf_path}")
        try:
            markdown_path = self.pdf_processor.process(
                str(pdf_path),
                str(paper_dir)
            )
            self.logger.info(f"PDF成功转换为Markdown: {markdown_path}")
            return markdown_path
        except Exception as e:
            self.logger.error(f"PDF转Markdown失败: {str(e)}")
            raise

    def _stage_md_to_json(self, pdf_path: Path, paper_dir: Path, 
                         paper_name: str, output_paths: dict) -> Path:
        """Markdown转结构化JSON阶段"""
        self.logger.info("开始将Markdown转换为JSON")
        try:
            markdown_path = output_paths.get('pdf2md')
            if not markdown_path:
                raise ValueError("未找到前序阶段生成的Markdown文件")

            output_path = self._get_stage_output_path('md2json', paper_dir, paper_name)
            json_path = self.md_processor.process(
                str(markdown_path),
                str(output_path)
            )
            self.logger.info(f"Markdown成功转换为JSON: {json_path}")
            return json_path
        except Exception as e:
            self.logger.error(f"Markdown转JSON失败: {str(e)}")
            raise

    def _stage_json_process(self, pdf_path: Path, paper_dir: Path, 
                          paper_name: str, output_paths: dict) -> Path:
        """JSON处理阶段"""
        self.logger.info("开始处理JSON文件")
        try:
            input_json_path = output_paths.get('md2json')
            if not input_json_path:
                raise ValueError("未找到前序阶段生成的JSON文件")
            
            output_path = self._get_stage_output_path('json_process', paper_dir, paper_name)
            processed_json_path = self.json_processor.process(
                str(input_json_path),
                str(output_path)
            )
            self.logger.info(f"JSON文件处理完成: {processed_json_path}")
            return processed_json_path
        except Exception as e:
            self.logger.error(f"JSON处理失败: {str(e)}")
            raise
            
    def _stage_tiling(self, pdf_path: Path, paper_dir: Path, 
                    paper_name: str, output_paths: dict) -> Path:
        """平铺阶段：将处理后的JSON文件进行平铺处理"""
        self.logger.info("开始平铺阶段")
        try:
            # 获取前一阶段处理好的JSON文件路径
            input_json_path = output_paths.get('json_process')
                
            if not input_json_path:
                raise ValueError("未找到可用于平铺的JSON文件，请确保已运行前序JSON处理阶段")
            
            # 构建输出文件路径
            output_path = self._get_stage_output_path('tiling', paper_dir, paper_name)
            
            # 调用平铺处理器进行平铺
            tiled_json_path = self.tiling_processor.process(
                str(input_json_path),
                str(output_path)
            )
            
            self.logger.info(f"JSON文件平铺完成: {tiled_json_path}")
            return tiled_json_path
        except Exception as e:
            self.logger.error(f"平铺阶段失败: {str(e)}", exc_info=True)
            raise

    def _stage_translate(self, pdf_path: Path, paper_dir: Path, 
                        paper_name: str, output_paths: dict) -> Path:
        """翻译阶段，使用TranslateProcessor进行JSON文件的翻译"""
        self.logger.info("开始翻译阶段")
        try:
            # 获取前一阶段处理好的JSON文件路径
            input_json_path = output_paths.get('tiling')  
                
            if not input_json_path:
                raise ValueError("未找到可用于翻译的JSON文件，请确保已运行前序平铺阶段")
            
            # 构建输出文件路径
            output_path = self._get_stage_output_path('translate', paper_dir, paper_name)
            
            # 调用翻译处理器进行翻译
            translated_json_path = self.translate_processor.process(
                str(input_json_path),
                str(output_path)
            )
            
            self.logger.info(f"JSON文件翻译完成: {translated_json_path}")
            return translated_json_path
        except Exception as e:
            self.logger.error(f"翻译阶段失败: {str(e)}", exc_info=True)
            raise

    def _stage_md_restore(self, pdf_path: Path, paper_dir: Path, 
                  paper_name: str, output_paths: dict) -> dict:
        """还原阶段：将JSON文件还原为中英文Markdown文档"""
        self.logger.info("开始还原阶段")
        try:
            # 获取前一阶段处理好的翻译JSON文件路径
            input_json_path = output_paths.get('translate')
                
            if not input_json_path:
                raise ValueError("未找到可用于还原的翻译JSON文件，请确保已运行前序翻译阶段")
            
            # 获取该阶段的预期输出路径字典，直接生成最终路径
            output_paths_dict = self._get_stage_output_path('md_restore', paper_dir, paper_name)
            output_path_en = output_paths_dict['en']
            output_path_zh = output_paths_dict['zh']
            
            # 调用还原处理器
            en_path, zh_path = self.restore_processor.process(
                str(input_json_path),
                str(output_path_en),
                str(output_path_zh)
            )
            
            self.logger.info(f"还原完成: 英文文档 {en_path}, 中文文档 {zh_path}")
            
            # 返回一个字典，包含两个输出路径
            return {
                'en': Path(en_path),
                'zh': Path(zh_path)
            }
        except Exception as e:
            self.logger.error(f"还原阶段失败: {str(e)}", exc_info=True)
            raise

    def _stage_extra_info(self, pdf_path: Path, paper_dir: Path, 
                paper_name: str, output_paths: dict) -> Path:
        """额外信息提取处理阶段，主要生成各章节的总结"""
        self.logger.info("开始额外信息提取阶段")
        try:
            # 获取前一阶段处理好的JSON文件路径，这里使用翻译阶段的输出作为输入
            input_json_path = output_paths.get('translate')
                
            if not input_json_path:
                raise ValueError("未找到可用于提取额外信息的JSON文件，请确保已运行前序翻译阶段")
            
            # 构建输出文件路径
            output_path = self._get_stage_output_path('extra_info', paper_dir, paper_name)
            
            # 调用额外信息处理器
            processed_json_path = self.extra_info_processor.process(
                str(input_json_path),
                str(output_path)
            )
            
            self.logger.info(f"额外信息提取完成: {processed_json_path}")
            return processed_json_path
        except Exception as e:
            self.logger.error(f"额外信息提取阶段失败: {str(e)}", exc_info=True)
            raise

    def _stage_rag(self, pdf_path: Path, paper_dir: Path, 
                paper_name: str, output_paths: dict) -> dict:
        """RAG处理阶段：生成用于检索增强生成的数据结构
        
        该阶段将生成三个文件：
        1. Markdown文件：用于RAG向量库的文本内容，以#节点key + 文段内容为基本单位
        2. 树结构JSON文件：包含论文的层次结构，与MD文件中的节点key对应
        3. 向量库：基于Markdown文件生成的向量库，用于检索增强生成
        """
        self.logger.info("开始RAG处理阶段")
        try:
            # 获取前一阶段处理好的JSON文件路径
            # 使用extra_info阶段的输出作为输入，因为它包含了额外的摘要信息
            input_json_path = output_paths.get('extra_info')
            
            if not input_json_path:
                # 如果没有extra_info阶段的输出，则使用translate阶段的输出
                input_json_path = output_paths.get('translate')
                
            if not input_json_path:
                raise ValueError("未找到可用于RAG处理的JSON文件，请确保已运行前序翻译或额外信息阶段")
            
            # 构建输出文件路径字典，直接生成最终路径
            output_paths_dict = self._get_stage_output_path('rag', paper_dir, paper_name)
            output_md_path = output_paths_dict['md']
            output_tree_json_path = output_paths_dict['tree_json']
            
            # 获取向量库路径
            vector_store_path = output_paths_dict['vector_store']
            
            # 调用RAG处理器
            md_path, tree_json_path, vector_store_path = self.rag_processor.process(
                str(input_json_path),
                str(output_md_path),
                str(output_tree_json_path),
                str(vector_store_path)
            )
            
            self.logger.info(
                f"RAG处理完成: Markdown文件 {md_path}, 树结构JSON {tree_json_path}, 向量库 {vector_store_path}"
            )
            
            # 返回一个字典，包含三个输出路径
            return {
                'md': Path(md_path),
                'tree_json': Path(tree_json_path),
                'vector_store': Path(vector_store_path)
            }
        except Exception as e:
            self.logger.error(f"RAG处理阶段失败: {str(e)}", exc_info=True)
            raise