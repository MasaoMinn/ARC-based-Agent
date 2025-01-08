package com.example.springwebtlias.service;

import com.example.springwebtlias.mapper.DeptMapper;
import com.example.springwebtlias.pojo.Dept;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public class DeptServiceImpl implements DeptService {

    @Autowired
   private DeptMapper deptMapper;

    @Override
    public List<Dept> list()
    {
        return deptMapper.list();
    }

    @Override
    public void delete(int id) {
        deptMapper.delete(id);
        return;
    }

    @Override
    public void add(Dept dept) {
        dept.setCreateTime(LocalDateTime.now());
        dept.setUpdateTime(LocalDateTime.now());
        deptMapper.add(dept);
        return;
    }

    @Override
    public Dept selectById(Integer id) {
       Dept dept = deptMapper.selectById(id);
        return dept;
    }

    @Override
    public void change(Dept dept) {
        dept.setUpdateTime(LocalDateTime.now());
        deptMapper.change(dept);
        return;
    }
}
