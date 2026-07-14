"""
聚合服务单元测试

测试四种聚合策略的正常情况和边界条件。
"""

import pytest
from online.services.aggregator_service import aggregate_results
from online.services.extraction_service import ExtractionService


class TestAggregatorService:
    """聚合服务测试"""

    # ==================== first_non_null 策略 ====================

    def test_first_non_null_basic(self):
        """取第一个非空值"""
        all_page_results = [
            [{"field_name": "amount", "value": None, "confidence": 0.0, "page": 1}],
            [{"field_name": "amount", "value": 100.0, "confidence": 0.9, "page": 2}],
            [{"field_name": "amount", "value": 200.0, "confidence": 0.8, "page": 3}],
        ]
        agg_rules = {"amount": {"strategy": "first_non_null"}, "default": {"strategy": "first_non_null"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] == 100.0
        assert decisions["amount"]["selected_page"] == 2
        assert "first" in decisions["amount"]["reason"]

    def test_first_non_null_all_none(self):
        """所有页均为空值"""
        all_page_results = [
            [{"field_name": "amount", "value": None, "confidence": 0.0, "page": 1}],
            [{"field_name": "amount", "value": None, "confidence": 0.0, "page": 2}],
        ]
        agg_rules = {"amount": {"strategy": "first_non_null"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] is None
        assert decisions["amount"]["selected_page"] is None
        assert "all_none" in decisions["amount"]["reason"]

    def test_first_non_null_first_page(self):
        """第一页即为非空"""
        all_page_results = [
            [{"field_name": "amount", "value": 50.0, "confidence": 0.9, "page": 1}],
            [{"field_name": "amount", "value": 100.0, "confidence": 0.9, "page": 2}],
        ]
        agg_rules = {"amount": {"strategy": "first_non_null"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] == 50.0
        assert decisions["amount"]["selected_page"] == 1

    # ==================== last_non_null 策略 ====================

    def test_last_non_null_basic(self):
        """取最后一个非空值"""
        all_page_results = [
            [{"field_name": "amount", "value": 100.0, "confidence": 0.9, "page": 1}],
            [{"field_name": "amount", "value": None, "confidence": 0.0, "page": 2}],
            [{"field_name": "amount", "value": 300.0, "confidence": 0.8, "page": 3}],
        ]
        agg_rules = {"amount": {"strategy": "last_non_null"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] == 300.0
        assert decisions["amount"]["selected_page"] == 3

    def test_last_non_null_all_none(self):
        """所有页均为空值"""
        all_page_results = [
            [{"field_name": "amount", "value": None, "confidence": 0.0, "page": 1}],
        ]
        agg_rules = {"amount": {"strategy": "last_non_null"}}

        fields, _ = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] is None

    # ==================== max_confidence 策略 ====================

    def test_max_confidence_basic(self):
        """取置信度最高的值"""
        all_page_results = [
            [{"field_name": "amount", "value": 100.0, "confidence": 0.7, "page": 1}],
            [{"field_name": "amount", "value": 200.0, "confidence": 0.95, "page": 2}],
            [{"field_name": "amount", "value": 300.0, "confidence": 0.8, "page": 3}],
        ]
        agg_rules = {"amount": {"strategy": "max_confidence"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] == 200.0
        assert decisions["amount"]["selected_page"] == 2

    def test_max_confidence_tie(self):
        """置信度相同时取页码较小的"""
        all_page_results = [
            [{"field_name": "amount", "value": 100.0, "confidence": 0.9, "page": 1}],
            [{"field_name": "amount", "value": 200.0, "confidence": 0.9, "page": 2}],
        ]
        agg_rules = {"amount": {"strategy": "max_confidence"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] == 100.0
        assert decisions["amount"]["selected_page"] == 1

    def test_max_confidence_best_none(self):
        """置信度最高但值为空"""
        all_page_results = [
            [{"field_name": "amount", "value": 100.0, "confidence": 0.8, "page": 1}],
            [{"field_name": "amount", "value": None, "confidence": 0.9, "page": 2}],
        ]
        agg_rules = {"amount": {"strategy": "max_confidence"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["amount"] is None
        assert decisions["amount"]["selected_page"] == 2

    # ==================== merge_lists 策略 ====================

    def test_merge_lists_basic(self):
        """按页码顺序合并列表"""
        all_page_results = [
            [{"field_name": "items", "value": ["a", "b"], "confidence": 0.9, "page": 1}],
            [{"field_name": "items", "value": ["c", "d"], "confidence": 0.9, "page": 2}],
        ]
        agg_rules = {"items": {"strategy": "merge_lists"}}

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["items"] == ["a", "b", "c", "d"]
        assert decisions["items"]["selected_page"] is None

    def test_merge_lists_with_none(self):
        """部分页为空时跳过"""
        all_page_results = [
            [{"field_name": "items", "value": ["a"], "confidence": 0.9, "page": 1}],
            [{"field_name": "items", "value": None, "confidence": 0.0, "page": 2}],
            [{"field_name": "items", "value": ["b"], "confidence": 0.9, "page": 3}],
        ]
        agg_rules = {"items": {"strategy": "merge_lists"}}

        fields, _ = aggregate_results(all_page_results, agg_rules)

        assert fields["items"] == ["a", "b"]

    def test_merge_lists_non_list(self):
        """非列表类型的值被跳过"""
        all_page_results = [
            [{"field_name": "items", "value": ["a"], "confidence": 0.9, "page": 1}],
            [{"field_name": "items", "value": "not_a_list", "confidence": 0.9, "page": 2}],
        ]
        agg_rules = {"items": {"strategy": "merge_lists"}}

        fields, _ = aggregate_results(all_page_results, agg_rules)

        assert fields["items"] == ["a"]

    # ==================== 多种字段混合 ====================

    def test_multiple_fields_different_strategies(self):
        """多个字段使用不同策略"""
        all_page_results = [
            [
                {"field_name": "invoice_no", "value": "INV-001", "confidence": 0.9, "page": 1},
                {"field_name": "items", "value": ["item1"], "confidence": 0.9, "page": 1},
            ],
            [
                {"field_name": "invoice_no", "value": "INV-001-dup", "confidence": 0.7, "page": 2},
                {"field_name": "items", "value": ["item2"], "confidence": 0.9, "page": 2},
            ],
        ]
        agg_rules = {
            "invoice_no": {"strategy": "first_non_null"},
            "items": {"strategy": "merge_lists"},
        }

        fields, decisions = aggregate_results(all_page_results, agg_rules)

        assert fields["invoice_no"] == "INV-001"
        assert fields["items"] == ["item1", "item2"]
        assert decisions["invoice_no"]["selected_page"] == 1

    def test_default_strategy(self):
        """未指定策略的字段使用默认值"""
        all_page_results = [
            [{"field_name": "note", "value": "hello", "confidence": 0.9, "page": 1}],
        ]
        agg_rules = {}

        fields, _ = aggregate_results(all_page_results, agg_rules)

        assert fields["note"] == "hello"

    def test_empty_results(self):
        """没有任何提取结果"""
        fields, decisions = aggregate_results([], {})
        assert fields == {}
        assert decisions == {}


class TestGetFieldsForPage:
    """_get_fields_for_page 测试"""

    def setup_method(self):
        self.service = ExtractionService.__new__(ExtractionService)

    def test_all_pages(self):
        """pages='all' 时所有页都提取"""
        profile = {"fields": {"amount": {"pages": "all"}}}
        fields_schema = {"amount": {"type": "number"}}

        result = self.service._get_fields_for_page(profile, fields_schema, 1, 3)
        assert len(result) == 1
        assert result[0]["field_name"] == "amount"

        result_page2 = self.service._get_fields_for_page(profile, fields_schema, 2, 3)
        assert len(result_page2) == 1

    def test_first_page(self):
        """pages='first' 只在第一页提取"""
        profile = {"fields": {"invoice_no": {"pages": "first"}}}
        fields_schema = {"invoice_no": {"type": "string"}}

        result_p1 = self.service._get_fields_for_page(profile, fields_schema, 1, 3)
        assert len(result_p1) == 1

        result_p2 = self.service._get_fields_for_page(profile, fields_schema, 2, 3)
        assert len(result_p2) == 0

    def test_last_page(self):
        """pages='last' 只在最后一页提取"""
        profile = {"fields": {"total": {"pages": "last"}}}
        fields_schema = {"total": {"type": "number"}}

        result_p1 = self.service._get_fields_for_page(profile, fields_schema, 1, 3)
        assert len(result_p1) == 0

        result_p3 = self.service._get_fields_for_page(profile, fields_schema, 3, 3)
        assert len(result_p3) == 1

    def test_specific_pages(self):
        """pages=[1,3] 只在指定页码提取"""
        profile = {"fields": {"header": {"pages": [1, 3]}}}
        fields_schema = {"header": {"type": "object"}}

        result_p1 = self.service._get_fields_for_page(profile, fields_schema, 1, 3)
        assert len(result_p1) == 1

        result_p2 = self.service._get_fields_for_page(profile, fields_schema, 2, 3)
        assert len(result_p2) == 0

        result_p3 = self.service._get_fields_for_page(profile, fields_schema, 3, 3)
        assert len(result_p3) == 1

    def test_field_type_inherited_from_schema(self):
        """字段类型从 fields_schema 继承"""
        profile = {"fields": {"amount": {"pages": "all", "prompt_hint": "金额"}}}
        fields_schema = {"amount": {"type": "number", "description": "总金额"}}

        result = self.service._get_fields_for_page(profile, fields_schema, 1, 1)
        assert result[0]["type"] == "number"

    def test_prompt_hint_fallback(self):
        """prompt_hint 未配置时回退到 schema 的 description"""
        profile = {"fields": {"amount": {"pages": "all"}}}
        fields_schema = {"amount": {"type": "number", "description": "总金额"}}

        result = self.service._get_fields_for_page(profile, fields_schema, 1, 1)
        assert result[0]["prompt_hint"] == "总金额"

    def test_post_process_inherited(self):
        """post_process 配置从 profile 透传"""
        profile = {"fields": {"amount": {"pages": "all", "post_process": "strip|to_number"}}}
        fields_schema = {"amount": {"type": "number"}}

        result = self.service._get_fields_for_page(profile, fields_schema, 1, 1)
        assert result[0]["post_process"] == "strip|to_number"