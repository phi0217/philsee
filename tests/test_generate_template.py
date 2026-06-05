"""
/generate_template 接口测试

测试模板自动生成功能。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from online.services.template_generator_service import (
    generate_template,
    generate_fields_config,
    generate_profile_config,
    generate_aggregation_config,
    TemplateGeneratorError,
    ConflictError,
)
from online.utils.version_helper import (
    generate_default_template_id,
    generate_template_version,
    check_config_version_exists,
    insert_config_version,
)
from online.utils.validator import (
    validate_fields_config,
    validate_profile_config,
    validate_aggregation_config,
)


# ============================================================
# 辅助函数测试
# ============================================================

class TestVersionHelper:
    """版本辅助函数测试"""

    def test_generate_default_template_id(self):
        """测试默认模板 ID 生成"""
        doc_type = "invoice"
        template_id = generate_default_template_id(doc_type)

        # 检查格式：{doc_type}_default_{timestamp}
        assert template_id.startswith("invoice_default_")
        # 时间戳格式：%Y%m%d%H%M%S
        timestamp_part = template_id.split("_default_")[1]
        assert len(timestamp_part) == 14
        # 验证可以解析为日期
        datetime.strptime(timestamp_part, "%Y%m%d%H%M%S")

    def test_generate_default_template_id_with_special_doc_type(self):
        """测试特殊文档类型的模板 ID 生成"""
        doc_type = "letter_of_credit"
        template_id = generate_default_template_id(doc_type)
        assert template_id.startswith("letter_of_credit_default_")

    @pytest.mark.asyncio
    async def test_generate_template_version_no_existing(self):
        """测试无现有版本时的版本号生成"""
        session = AsyncMock(spec=AsyncSession)

        # Mock 返回空版本列表
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        session.execute.return_value = mock_result

        version = await generate_template_version(session, "test_template")
        assert version == "v1.0.0"

    @pytest.mark.asyncio
    async def test_generate_template_version_with_existing(self):
        """测试有现有版本时的版本号递增"""
        session = AsyncMock(spec=AsyncSession)

        # Mock 返回已有版本列表
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = ["v1.0.0", "v1.0.1", "v1.0.3"]
        session.execute.return_value = mock_result

        version = await generate_template_version(session, "test_template")
        assert version == "v1.0.4"

    @pytest.mark.asyncio
    async def test_generate_template_version_with_provided(self):
        """测试提供版本号时直接使用"""
        session = AsyncMock(spec=AsyncSession)

        version = await generate_template_version(session, "test_template", "v2.0.0")
        assert version == "v2.0.0"


# ============================================================
# 校验函数测试
# ============================================================

class TestValidator:
    """配置校验测试"""

    def test_validate_fields_config_valid(self):
        """测试有效的 fields 配置"""
        config = {
            "fields": {
                "invoice_number": {
                    "type": "string",
                    "description": "发票号码"
                },
                "amount": {
                    "type": "number",
                    "description": "金额"
                }
            }
        }
        is_valid, error_msg = validate_fields_config(config)
        assert is_valid is True
        assert error_msg == ""

    def test_validate_fields_config_missing_fields(self):
        """测试缺少 fields 字段"""
        config = {"something": "else"}
        is_valid, error_msg = validate_fields_config(config)
        assert is_valid is False
        assert "fields" in error_msg

    def test_validate_fields_config_invalid_type(self):
        """测试无效的字段类型"""
        config = {
            "fields": {
                "field1": {
                    "type": "invalid_type"
                }
            }
        }
        is_valid, error_msg = validate_fields_config(config)
        assert is_valid is False
        assert "invalid_type" in error_msg

    def test_validate_profile_config_valid(self):
        """测试有效的 profile 配置"""
        config = {
            "doc_type": "invoice",
            "fields": {
                "invoice_number": {
                    "prompt_hint": "提取发票号码"
                }
            }
        }
        is_valid, error_msg = validate_profile_config(config, "invoice")
        assert is_valid is True

    def test_validate_profile_config_doc_type_mismatch(self):
        """测试 doc_type 不匹配"""
        config = {
            "doc_type": "invoice",
            "fields": {}
        }
        is_valid, error_msg = validate_profile_config(config, "letter_of_credit")
        assert is_valid is False
        assert "不一致" in error_msg

    def test_validate_aggregation_config_valid(self):
        """测试有效的 aggregation 配置"""
        config = {
            "fields": {
                "invoice_number": {
                    "strategy": "first"
                },
                "items": {
                    "strategy": "concat"
                }
            }
        }
        profile_fields = ["invoice_number", "items", "amount"]
        is_valid, error_msg = validate_aggregation_config(config, profile_fields)
        assert is_valid is True

    def test_validate_aggregation_config_invalid_field(self):
        """测试 aggregation 包含不存在的字段"""
        config = {
            "fields": {
                "unknown_field": {
                    "strategy": "first"
                }
            }
        }
        profile_fields = ["invoice_number", "amount"]
        is_valid, error_msg = validate_aggregation_config(config, profile_fields)
        assert is_valid is False
        assert "unknown_field" in error_msg

    def test_validate_aggregation_config_invalid_strategy(self):
        """测试无效的聚合策略"""
        config = {
            "fields": {
                "amount": {
                    "strategy": "invalid_strategy"
                }
            }
        }
        profile_fields = ["amount"]
        is_valid, error_msg = validate_aggregation_config(config, profile_fields)
        assert is_valid is False
        assert "invalid_strategy" in error_msg


# ============================================================
# 服务函数测试
# ============================================================

class TestTemplateGeneratorService:
    """模板生成服务测试"""

    @pytest.mark.asyncio
    async def test_generate_fields_config_mock_vlm(self):
        """测试 fields 配置生成（Mock VLM）"""
        images_base64 = ["data:image/jpeg;base64,test_image_data"]
        vlm_config = {
            "endpoint": "http://test.example.com/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-key",
            "temperature": 0.0,
            "max_retries": 2,
            "timeout": 30.0,
        }

        mock_response = '{"fields": {"test_field": {"type": "string", "description": "测试字段"}}}'

        with patch("online.services.template_generator_service._call_vlm_with_images") as mock_call:
            mock_call.return_value = (mock_response, 0.9)

            config = await generate_fields_config(images_base64, vlm_config)

            assert "fields" in config
            assert "test_field" in config["fields"]

    @pytest.mark.asyncio
    async def test_generate_profile_config_mock_vlm(self):
        """测试 profile 配置生成（Mock VLM）"""
        images_base64 = ["data:image/jpeg;base64,test_image_data"]
        fields_config = {
            "fields": {
                "invoice_number": {"type": "string", "description": "发票号码"}
            }
        }
        doc_type = "invoice"
        vlm_config = {
            "endpoint": "http://test.example.com/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-key",
            "temperature": 0.0,
            "max_retries": 2,
            "timeout": 30.0,
        }

        mock_response = '''{
            "doc_type": "invoice",
            "fields": {
                "invoice_number": {
                    "prompt_hint": "提取发票号码",
                    "pages": "first"
                }
            }
        }'''

        with patch("online.services.template_generator_service._call_vlm_with_images") as mock_call:
            mock_call.return_value = (mock_response, 0.9)

            config = await generate_profile_config(images_base64, doc_type, fields_config, vlm_config)

            assert config["doc_type"] == "invoice"
            assert "invoice_number" in config["fields"]

    @pytest.mark.asyncio
    async def test_generate_aggregation_config_mock_vlm(self):
        """测试 aggregation 配置生成（Mock VLM）"""
        profile_field_names = ["invoice_number", "amount", "items"]
        vlm_config = {
            "endpoint": "http://test.example.com/v1/chat/completions",
            "model": "test-model",
            "api_key": "test-key",
            "temperature": 0.0,
            "max_retries": 2,
            "timeout": 30.0,
        }

        mock_response = '''{
            "fields": {
                "invoice_number": {"strategy": "first"},
                "amount": {"strategy": "sum"},
                "items": {"strategy": "concat"}
            }
        }'''

        with patch("online.services.template_generator_service.call_vlm") as mock_call:
            mock_call.return_value = (mock_response, 0.9)

            config = await generate_aggregation_config(profile_field_names, vlm_config)

            assert "fields" in config
            assert config["fields"]["invoice_number"]["strategy"] == "first"


# ============================================================
# 集成测试（需要数据库）
# ============================================================

class TestGenerateTemplateIntegration:
    """模板生成集成测试"""

    @pytest.mark.asyncio
    async def test_generate_template_conflict_error(self):
        """测试模板 ID 冲突"""
        session = AsyncMock(spec=AsyncSession)

        # Mock 返回已存在
        with patch("online.services.template_generator_service.check_config_version_exists") as mock_check:
            mock_check.return_value = True

            with pytest.raises(ConflictError):
                await generate_template(
                    session=session,
                    images_base64=["data:image/jpeg;base64,test"],
                    doc_type="invoice",
                    template_id=None,
                    version=None,
                    vlm_config={
                        "endpoint": "http://test.example.com",
                        "model": "test-model",
                        "api_key": "test-key",
                        "temperature": 0.0,
                    },
                )


# ============================================================
# 运行测试
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
