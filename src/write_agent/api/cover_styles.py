"""
封面风格管理 API
"""
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from write_agent.models.cover_style import CoverStyle
from write_agent.core.database import engine

router = APIRouter(prefix="/covers/styles", tags=["封面风格管理"])


class CoverStyleCreate(BaseModel):
    """创建封面风格请求"""
    name: str
    prompt_template: str
    description: str | None = None


class CoverStyleResponse(BaseModel):
    """封面风格响应"""
    id: int
    name: str
    prompt_template: str
    description: str | None
    is_active: bool
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True


@router.post("", response_model=CoverStyleResponse)
def create_cover_style(data: CoverStyleCreate):
    """创建封面风格"""
    with Session(engine) as session:
        # 检查名称是否已存在
        existing = session.exec(
            select(CoverStyle).where(CoverStyle.name == data.name)
        ).first()
        if existing:
            raise HTTPException(status_code=400, detail="风格名称已存在")

        cover_style = CoverStyle(
            name=data.name,
            prompt_template=data.prompt_template,
            description=data.description,
            is_active=True
        )
        session.add(cover_style)
        session.commit()
        session.refresh(cover_style)

        return CoverStyleResponse(
            id=cover_style.id,
            name=cover_style.name,
            prompt_template=cover_style.prompt_template,
            description=cover_style.description,
            is_active=cover_style.is_active,
            created_at=cover_style.created_at.isoformat(),
            updated_at=cover_style.updated_at.isoformat()
        )


@router.get("", response_model=List[CoverStyleResponse])
def list_cover_styles():
    """获取封面风格列表"""
    with Session(engine) as session:
        styles = session.exec(
            select(CoverStyle)
            .where(CoverStyle.is_active == True)
            .order_by(CoverStyle.created_at.desc())
        ).all()

        return [
            CoverStyleResponse(
                id=s.id,
                name=s.name,
                prompt_template=s.prompt_template,
                description=s.description,
                is_active=s.is_active,
                created_at=s.created_at.isoformat(),
                updated_at=s.updated_at.isoformat()
            )
            for s in styles
        ]


@router.get("/{style_id}", response_model=CoverStyleResponse)
def get_cover_style(style_id: int):
    """获取封面风格详情"""
    with Session(engine) as session:
        style = session.get(CoverStyle, style_id)
        if not style or not style.is_active:
            raise HTTPException(status_code=404, detail="风格不存在")

        return CoverStyleResponse(
            id=style.id,
            name=style.name,
            prompt_template=style.prompt_template,
            description=style.description,
            is_active=style.is_active,
            created_at=style.created_at.isoformat(),
            updated_at=style.updated_at.isoformat()
        )


@router.delete("/{style_id}")
def delete_cover_style(style_id: int):
    """删除封面风格（软删除）"""
    with Session(engine) as session:
        style = session.get(CoverStyle, style_id)
        if not style:
            raise HTTPException(status_code=404, detail="风格不存在")

        style.is_active = False
        session.commit()

        return {"message": "删除成功"}
