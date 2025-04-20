import logging
import sys
from typing import Optional, List, Dict, Any, Generator
from openai import OpenAI
from langchain_huggingface import HuggingFaceEmbeddings

# API配置
API_BASE_URL = "YOUR_API_URL"
API_KEY = "YOUR_API_KEY"

TTS_GROUP_ID = "YOUR_MINIMAX_GROUP_ID"
TTS_API_KEY = "YOUR_MINIMAX_API_KEY"

# 嵌入模型配置
EMBEDDING_MODEL_NAME = "BAAI/bge-m3"

# 日志配置
def setup_logging():
    """设置日志配置为控制台输出"""
    # 设置日志格式
    log_format = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建一个根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 创建并配置控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(log_format)
    
    # 清除任何现有的处理器
    root_logger.handlers.clear()
    # 添加控制台处理器
    root_logger.addHandler(console_handler)

# LLM客户端
class LLMClient:
    _instance: Optional['LLMClient'] = None
    
    def __new__(cls, *args, **kwargs):
        """单例模式实现"""
        if cls._instance is None:
            cls._instance = super(LLMClient, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self, api_key=None, base_url=None):
        """初始化LLM客户端"""
        if self._initialized:
            return
            
        self.api_key = api_key or API_KEY
        self.base_url = base_url or API_BASE_URL
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url
        )
        self._initialized = True
        
    def chat(self, messages: List[Dict[str, Any]], temperature=0.5, stream=True) -> str:
        """与LLM交互
        
        Args:
            messages: 消息列表
            temperature: 温度参数，控制随机性
            stream: 是否使用流式输出
            
        Returns:
            str: LLM响应内容
        """
        try:
            response = self.client.chat.completions.create(
                model="deepseek-v3-250324",
                messages=messages,
                temperature=temperature,
                stream=stream
            )
            
            if stream:
                full_response = ""
                for chunk in response:
                    if chunk.choices[0].delta.content is not None:
                        content = chunk.choices[0].delta.content
                        print(content, end='', flush=True)
                        full_response += content
                print()
                return full_response
            else:
                return response.choices[0].message.content
                
        except Exception as e:
            print(f"LLM调用出错: {str(e)}")
            raise

    def chat_stream_by_sentence(self, messages: List[Dict[str, Any]], temperature=0.5) -> Generator[str, None, str]:
        """与LLM交互，按句子流式返回结果
        
        Args:
            messages: 消息列表
            temperature: 温度参数，控制随机性
            
        Yields:
            str: 每个完整句子
            
        Returns:
            str: 完整响应
        """
        try:
            response = self.client.chat.completions.create(
                model="deepseek-v3-250324",
                messages=messages,
                temperature=temperature,
                stream=True
            )
            
            full_response = ""
            current_sentence = ""
            
            # 中文的结束标点 - 这些可以直接作为句子结束符
            cn_end_marks = '。！？'
            # 英文的结束标点 - 这些需要检查后续字符
            en_end_marks = '.!?;'
            
            for chunk in response:
                if chunk.choices[0].delta.content is not None:
                    content = chunk.choices[0].delta.content
                    current_sentence += content
                    full_response += content
                    
                    # 情况1: 包含中文结束标点，直接作为句子结束
                    if any(char in cn_end_marks for char in content):
                        sentence = current_sentence.strip()
                        # 只有句子长度超过10字才yield
                        if sentence and len(sentence) >= 10:
                            yield sentence
                            current_sentence = ""
                    
                    # 情况2: 检查英文结束标点后是否跟着空格或换行符
                    elif any(char in en_end_marks for char in content):
                        # 检查当前积累的句子中是否有 "英文结束标点+空格/换行" 的模式
                        import re
                        # 匹配 句点/感叹号/问号/分号 后跟空白字符的模式
                        matches = list(re.finditer(r'[.!?;][\s\n]', current_sentence))
                        
                        if matches:
                            # 找到最后一个匹配，在该位置分割句子
                            last_match = matches[-1]
                            end_position = last_match.end() - 1  # 减1是为了不包含空格/换行符
                            
                            sentence = current_sentence[:end_position].strip()
                            remaining = current_sentence[end_position:].strip()
                            
                            # 只有句子长度超过10字才yield
                            if sentence and len(sentence) >= 10:
                                yield sentence
                                current_sentence = remaining
            
            # 处理剩余内容
            if current_sentence.strip():
                sentence = current_sentence.strip()
                if sentence:
                    yield sentence
            
            return full_response
                
        except Exception as e:
            print(f"LLM调用出错: {str(e)}")
            yield f"生成回复时出错: {str(e)}"
            raise


# 嵌入模型
class EmbeddingModel:
    _instance: Optional[HuggingFaceEmbeddings] = None

    @classmethod
    def get_instance(cls) -> HuggingFaceEmbeddings:
        """获取嵌入模型单例"""
        if cls._instance is None:
            # 检查CUDA可用性
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                elif torch.mps.is_available():
                    device = "mps"
                elif torch.xpu.is_available():
                    device = "xpu"
                else:
                    device = "cpu"
            except ImportError:
                device = "cpu"
                
            logging.info(f"初始化嵌入模型: {EMBEDDING_MODEL_NAME}，使用设备: {device}")
            
            cls._instance = HuggingFaceEmbeddings(
                model_name=EMBEDDING_MODEL_NAME,
                model_kwargs={"device": device},
                encode_kwargs={"normalize_embeddings": True}
            )
        return cls._instance

# 使用示例
if __name__ == "__main__":
    # 设置日志
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # LLM客户端示例
    logger.info("测试LLM客户端...")
    llm = LLMClient()
    messages = [
        {"role": "user", "content": "你好"}
    ]
    response = llm.chat(messages)
    logger.info(f"LLM响应: {response}")
    
    # 嵌入模型示例
    logger.info("测试嵌入模型...")
    text = "这是一个测试文本"
    embedding_model = EmbeddingModel.get_instance()
    embedding = embedding_model.embed_query(text)
    logger.info(f"嵌入向量维度: {len(embedding)}")