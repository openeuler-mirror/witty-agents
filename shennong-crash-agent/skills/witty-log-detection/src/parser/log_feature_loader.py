import os
import yaml
from src.enum.log import LogTypeEnum
from src.config.config import Config, ConfigModel

feature_directory = os.path.join(os.path.dirname(__file__), 'log_features')
config = Config().get_config()

class BaseLogFeature:
    """基础日志特征类"""

    def __init__(self, config):
        self.keywords_regex_and_scores = config.get('keywords_regex_and_scores', {})
        self.mandatory = config.get('mandatory', {})
        self.capture_patterns = config.get('capture_patterns', {})


class LogFeatureLoader:
    """日志特征加载器"""

    @staticmethod
    def load(config: ConfigModel = config, directory: str = feature_directory):
        """
        从指定目录加载日志特征

        Args:
            directory: 日志特征文件目录路径

        Returns:
            日志类型到特征对象的映射
        """
        log_feature_mapping = {}
        log_types_to_load = config.log_parse_config.log_types_to_load

        if not log_types_to_load:
            target_files = [f for f in os.listdir(directory) if f.endswith('.yaml')]
        else:
            target_files = [f"{t.name.lower()}_log_feature.yaml" for t in log_types_to_load]

        # 2. 统一遍历读取
        for filename in target_files:
            filepath = os.path.join(directory, filename)
            if not os.path.exists(filepath):
                continue

            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_config = yaml.safe_load(f)
                    if not file_config:
                        continue

                # 解析日志类型
                log_type_name = os.path.splitext(filename)[0].replace('_log_feature', '').upper()
                log_type = getattr(LogTypeEnum, log_type_name, None)
                if log_type:
                    log_feature_mapping[log_type] = BaseLogFeature(file_config)
            except Exception:
                pass

        return log_feature_mapping


# 动态加载日志特征配置
log_feature_class_mapping = LogFeatureLoader.load()
