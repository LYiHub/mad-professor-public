import re
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass, field
from collections import defaultdict
from pathlib import Path

# 配置日志
logger = logging.getLogger(__name__)

@dataclass
class Section:
    title: str            # 完整标题（包含编号和文本）
    number: str           # 章节编号（如 "1.2.3"）
    level: int           # 层级深度（根据编号中的点数确定）
    content: List[str]   # 章节内容，每个段落作为列表的一个元素
    raw_title: str       # 不含编号的标题文本
    type: Optional[str] = None   # 章节类型,如 'abstract', 'references'

class MarkdownProcessor:
    """Markdown处理器：将Markdown解析为结构化JSON"""

    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

        # 匹配标题的正则表达式（匹配 # 开头的行）
        self.title_pattern = re.compile(r'^(#+)\s*(\S.*?)$')
        
        # 匹配摘要标题的正则表达式（匹配 ABSTRACT 或其变体）
        self.abstract_pattern = re.compile(r'^#?\s*(?:\d+\.)?\s*(?:ABSTRACT|Abstract|abstract)')
        
        # 匹配参考文献标题的正则表达式
        self.reference_pattern = re.compile(r'^#?\s*(?:\d+\.)?\s*(?:REFERENCES?|References?|references?)')

        # 匹配不带#的参考文献行
        self.reference_line_pattern = re.compile(r'^(?:REFERENCES?|References?|references?)(?:\s*:|\s*\.)?\s*$')
        
        # 匹配章节编号的正则表达式（如 1.2.3）
        self.section_number_pattern = re.compile(r'^(\d+(?:\.\d+)*)(\.?)\s*(.*?)$')
        
        # 匹配可能的标题行（非 # 开头，但包含数字编号和大写标题）
        self.potential_title_pattern = re.compile(r'^(?!#)(\d+(?:\.\d+)*)\s+([A-Z][A-Z\s\d:]+(?:\s*[A-Z][A-Za-z\s\d:]+)*)')

        # 匹配可能的图表说明
        self.figure_table_pattern = re.compile(r'''
            ^(?:
                (?:Figure|Fig\.|Table|Tab\.)          # Figure, Fig., Table, Tab.
                (?:\s+\(?\d+(?:\.\d+)?\)?\.?:?)       # (1), 1:, 1., (1.1), 1.1:, etc.
                |
                (?:IMAGE|DIAGRAM)                     # IMAGE, DIAGRAM
                (?:\s+\d+:?)                          # 1:, 1
                |
                (?:Figure|Table)                      # Figure, Table  
                (?:\s+[IVX]+:?)                       # I:, II, III, IV, etc.
            )
            ''', re.IGNORECASE | re.VERBOSE)

        # 匹配Markdown格式的图片
        self.image_pattern = re.compile(r'^!\[.*?\]\(.*?\)')
        
        # 匹配数学公式块
        self.latex_block_pattern = re.compile(r'^\$\$')

        self.logger.debug("初始化Markdown处理器完成")
        
    def parse_section_number(self, title: str) -> tuple[str, str, int]:
        """解析章节标题，提取编号、原始标题和层级深度"""
        match = self.section_number_pattern.match(title)
        if match:
            number, dot, raw_title = match.groups()
            # 忽略末尾的点号
            level = len(number.split('.'))  # 通过点号数量确定层级
            return number.strip(), raw_title.strip(), level
        return '', title.strip(), 1  # 如果没有编号，返回默认值

    def parse_references(self, content: str) -> List[str]:
        """将参考文献内容解析为列表"""
        # 按换行符分割内容并过滤空行
        references = [line.strip() for line in content.split('\n') if line.strip()]
        return references

    def parse_content(self, content: List[str]) -> List[str]:
        """将内容解析为段落列表"""
        text = '\n'.join(content)
        paragraphs = []
        current_para = []
        
        in_latex_block = False
        latex_content = []
        
        for line in text.split('\n'):
            line = line.strip()
            
            # 检查是否是LaTeX块的开始或结束
            if self.latex_block_pattern.match(line):
                if in_latex_block:
                    # LaTeX块结束
                    latex_content.append(line)
                    paragraphs.append('\n'.join(latex_content))
                    latex_content = []
                    in_latex_block = False
                else:
                    # LaTeX块开始
                    if current_para:
                        paragraphs.append('\n'.join(current_para).strip())
                        current_para = []
                    latex_content.append(line)
                    in_latex_block = True
                continue
                
            if in_latex_block:
                latex_content.append(line)
                continue
            
            if not line:
                if current_para:
                    paragraphs.append('\n'.join(current_para).strip())
                    current_para = []
                continue
                
            # 检查是否是图片引用或图表说明
            if self.image_pattern.match(line) or self.figure_table_pattern.match(line):
                if current_para:
                    paragraphs.append('\n'.join(current_para).strip())
                    current_para = []
                paragraphs.append(line)
                continue
                
            current_para.append(line)
            
        if current_para:
            paragraphs.append('\n'.join(current_para).strip())
            
        return paragraphs

    def find_missing_sections(self, content: str, current_prefix: str) -> Tuple[List[Section], List[str]]:
        """在章节内容中查找可能遗漏的章节标题，并重新分配内容"""
        missing_sections = []
        lines = content.split('\n')
        section_start_indices = []
        
        # 查找所有可能的章节标题行
        for i, line in enumerate(lines):
            match = self.potential_title_pattern.match(line)
            if match:
                number, title_text = match.groups()
                # 只处理与当前前缀匹配的章节
                if number.startswith(current_prefix):
                    section_start_indices.append((i, number, title_text))
        
        if not section_start_indices:
            return [], self.parse_content(lines)
            
        # 更新原章节的内容（只保留第一个遗漏章节之前的内容）
        original_content = self.parse_content(lines[:section_start_indices[0][0]])
        
        # 处理找到的每个章节
        for idx in range(len(section_start_indices)):
            start_idx, number, title_text = section_start_indices[idx]
            # 确定章节内容的结束位置
            end_idx = section_start_indices[idx + 1][0] if idx < len(section_start_indices) - 1 else len(lines)
            section_content = self.parse_content(lines[start_idx + 1:end_idx])
            
            # 解析章节信息并创建 Section 对象
            number, raw_title, level = self.parse_section_number(f"{number} {title_text}")
            missing_sections.append(Section(
                title=f"{number} {title_text}",
                number=number,
                level=level,
                content=section_content,
                raw_title=raw_title
            ))
        
        return missing_sections, original_content

    def remove_empty_sections(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """递归移除内容和子章节都为空的章节"""
        if not sections:
            return []

        result = []
        for section in sections:
            # 递归处理子章节
            if 'children' in section:
                section['children'] = self.remove_empty_sections(section['children'])
            
            # 检查章节是否为空（没有内容且没有子章节）
            content_empty = not section.get('content', [])
            children_empty = not section.get('children', [])
            references_empty = not section.get('references', [])
            
            # 如果章节不为空，或者有参考文献，保留该章节
            if not (content_empty and children_empty and references_empty):
                result.append(section)

        return result

    def check_section_continuity(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """检查同级章节的编号连续性，查找并补充遗漏的章节"""
        # 按章节编号排序
        sections.sort(key=lambda x: int(x['number'].split('.')[-1]))
        
        all_sections = sections.copy()
        section_numbers = [int(s['number'].split('.')[-1]) for s in sections]
        
        # 检查相邻章节编号的连续性
        i = 0
        while i < len(section_numbers) - 1:
            current_num = section_numbers[i]
            next_num = section_numbers[i + 1]
            
            # 如果存在编号跳跃
            if next_num - current_num > 1:
                current_section = sections[i]
                # 构造章节编号前缀
                prefix = '.'.join(current_section['number'].split('.')[:-1])
                if prefix:
                    prefix += '.'
                
                # 在当前章节内容中查找遗漏的章节
                missing_sections, updated_content = self.find_missing_sections(
                    '\n'.join(current_section['content']), 
                    prefix
                )
                
                if missing_sections:
                    print(f"在 {current_section['number']} 之后找到遗漏的章节：")
                    for section in missing_sections:
                        print(f"  - {section.title}")
                    
                    # 更新原章节的内容
                    current_section['content'] = updated_content
                    
                    # 将找到的章节插入到适当位置
                    for missing_section in missing_sections:
                        missing_dict = vars(missing_section)
                        # 确保每个章节字典都有 children 字段
                        missing_dict['children'] = []
                        # 找到正确的插入位置
                        insert_idx = next((j for j, s in enumerate(all_sections) 
                                        if s['number'] > missing_section.number), len(all_sections))
                        all_sections.insert(insert_idx, missing_dict)
                    
                    # 更新章节编号列表
                    section_numbers = [int(s['number'].split('.')[-1]) for s in all_sections]
                    i = 0  # 重新开始检查，因为可能有新的不连续性
                    continue
            
            i += 1
        
        return all_sections

    def build_hierarchy(self, sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """构建章节的层级结构"""
        hierarchy = []
        section_map = {}  # 用于快速查找章节
        level_groups = defaultdict(list)  # 按父章节分组的子章节
        
        # 第一次遍历：构建基本的层级关系
        for section in sections:
            section['children'] = []
            if not section['number']:  # 处理没有编号的章节
                hierarchy.append(section)
                continue
                
            numbers = section['number'].split('.')
            
            if len(numbers) == 1:  # 顶层章节
                hierarchy.append(section)
                section_map[section['number']] = section
            else:
                parent_number = '.'.join(numbers[:-1])
                if parent_number in section_map:
                    # 将同级章节归类
                    level_groups[parent_number].append(section)
                    section_map[section['number']] = section
                else:
                    # 如果找不到父章节，作为顶层章节处理
                    hierarchy.append(section)
                    section_map[section['number']] = section
        
        # 第二次遍历：处理每组同级章节
        for parent_number, group in level_groups.items():
            # 检查同级章节的连续性
            updated_group = self.check_section_continuity(group)
            
            # 更新父章节的 children
            if parent_number in section_map:
                section_map[parent_number]['children'] = updated_group
                
                # 更新 section_map
                for section in updated_group:
                    section_map[section['number']] = section
        
        return hierarchy

    def parse(self, content: str) -> Dict[str, Any]:
        """解析整个 Markdown 文档"""
        lines = content.split('\n')
        result = {
            'title': '',           # 文档标题
            'authors_info': '',    # 作者信息
            'sections': []         # 章节列表
        }
        
        current_section = None     # 当前正在处理的章节
        current_content = []       # 当前章节的内容行
        collecting_authors = False # 是否正在收集作者信息
        in_references = False      # 是否已到参考文献部分
        authors_content = []       # 作者信息内容
        has_started = False       # 文档解析是否已开始
        
        # 逐行处理文档
        for line in lines:
            title_match = self.title_pattern.match(line)

            # 检查是否是非标准格式的参考文献行
            reference_line_match = None
            if not in_references and not title_match:
                reference_line_match = self.reference_line_pattern.match(line)
            
            # 跳过文档开始前的空行
            if not has_started and not title_match:
                continue

            # 处理仅包含 # 但后面无内容的行
            if line.strip().startswith('#') and not title_match:
                # 直接忽略这一行，不作为内容处理
                continue
            

            # 处理非标准格式的参考文献行
            if reference_line_match:
                # 保存当前章节（如果有）
                if current_section:
                    current_section.content = self.parse_content(current_content)
                    result['sections'].append(vars(current_section))
                
                # 创建新的参考文献章节
                current_section = Section(
                    title="REFERENCES",
                    number="",
                    level=1,
                    content=[],
                    raw_title="REFERENCES",
                    type='references'
                )
                # 提取参考文献行中REFERENCES后面的内容作为第一条参考文献
                reference_content = re.sub(r'^(?:REFERENCES?|References?|references?)\s*', '', line).strip()
                current_content = [reference_content] if reference_content else []
                in_references = True
                continue

            elif title_match:
                heading_level = len(title_match.group(1))  # 标题级别（# 的数量）
                title_text = title_match.group(2).strip()  # 标题文本
                
                # 处理文档标题
                if not has_started:
                    result['title'] = title_text
                    # collecting_authors = True
                    has_started = True
                    continue
                
                # 处理摘要部分
                if self.abstract_pattern.match(line):
                    # 获取完整的作者信息文本
                    authors_text = '\n'.join(authors_content).strip()
                    authors_lines = authors_text.split('\n')
                    
                    # 使用已有的正则表达式筛选图片和图表说明
                    image_lines = []
                    clean_authors_lines = []
                    
                    for line in authors_lines:
                        if self.image_pattern.match(line) or self.figure_table_pattern.match(line):
                            image_lines.append(line)
                        else:
                            clean_authors_lines.append(line)
                    
                    # 保存清理后的作者信息
                    result['authors_info'] = '\n'.join(clean_authors_lines).strip()
                    collecting_authors = False
                    
                    # 创建 abstract 章节
                    number, raw_title, level = self.parse_section_number(title_text)
                    current_section = Section(
                        title=title_text,
                        number=number,
                        level=level,
                        content=[],
                        raw_title=raw_title,
                        type='abstract'
                    )
                    current_content = []
                    # 将找到的图片信息添加到 current_content
                    current_content.extend(image_lines)
                    continue
                
                # 收集作者信息
                if collecting_authors:
                    authors_content.append(title_text)
                    continue
                
                # 保存当前章节并开始新章节
                if current_section and not collecting_authors:
                    if in_references:
                        # 如果是参考文献章节，将内容解析为列表
                        current_section.content = self.parse_references('\n'.join(current_content))
                        result['sections'].append(vars(current_section))
                        break  # 处理完参考文献后直接跳出
                    else:
                        # 如果是摘要章节，需要特殊处理
                        if self.abstract_pattern.match(current_section.title):
                            # 分离图片/图表内容和其他内容
                            parsed_content = []
                            other_lines = []
                            
                            for line in current_content:
                                if self.image_pattern.match(line) or self.figure_table_pattern.match(line):
                                    # 将图片和图表说明作为单独的项
                                    parsed_content.append(line)
                                else:
                                    other_lines.append(line)
                            
                            # 将其他内容作为一个整体添加
                            if other_lines:
                                parsed_content.extend(self.parse_content(other_lines))
                                
                            current_section.content = parsed_content
                        else:
                            current_section.content = self.parse_content(current_content)
                        
                        result['sections'].append(vars(current_section))
                
                # 创建新章节
                number, raw_title, level = self.parse_section_number(title_text)
                current_section = Section(
                    title=title_text,
                    number=number,
                    level=level,
                    content=[],
                    raw_title=raw_title
                )
                current_content = []
                
                # 检查是否进入参考文献部分
                if self.reference_pattern.match(line):
                    in_references = True
                    current_section.type = 'references'
                    
            else:
                # 收集当前行的内容
                if collecting_authors:
                    authors_content.append(line)
                else:
                    current_content.append(line)
        
        # 构建层级结构（包含连续性检查）
        result['sections'] = self.build_hierarchy(result['sections'])

        # 移除空章节
        result['sections'] = self.remove_empty_sections(result['sections'])
        
        return result

    def process(self, markdown_path: str, output_path: str) -> Path:
        """将原来独立的 process_markdown_file 函数集成为类方法"""
        try:
            markdown_path = Path(markdown_path)
            output_path = Path(output_path)
            
            # 读取文件
            self.logger.info(f"开始解析Markdown文件: {markdown_path}")
            content = markdown_path.read_text(encoding='utf-8')
            
            # 使用原有的 parse 方法解析
            result = self.parse(content)
            
            # 保存结果
            self.logger.info(f"保存解析结果到: {output_path}")
            output_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2),
                encoding='utf-8'
            )
            
            return output_path
            
        except Exception as e:
            self.logger.error(f"Markdown处理失败: {str(e)}", exc_info=True)
            raise

if __name__ == "__main__":
    processor = MarkdownProcessor()
    try:
        json_path = processor.process("input.md", "output.json")
    except Exception as e:
        print(f"处理失败：{e}")